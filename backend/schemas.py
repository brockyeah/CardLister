"""Pydantic schemas for request/response validation."""
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


# How far ahead of our own clock a sale may be dated. A sale is an event that
# has already happened, so the only reason to accept anything ahead of "now" at
# all is clock skew: the client submits an instant built from *its* clock, and
# the two need not agree. A day of slack covers that with room to spare while
# still rejecting the mistyped year (2062) this bound exists for. Backdating is
# deliberately unbounded — recording a sale weeks later is ordinary, and a floor
# would reject it.
SOLD_AT_MAX_SKEW = timedelta(days=1)


def normalize_sold_at(value: datetime) -> datetime:
    """A submitted sale instant as naive UTC — the representation everything
    downstream assumes (`mark_sold`'s own fallback is `datetime.utcnow()`).

    Normalizing is what makes the future-date bound sound rather than
    decorative: SQLAlchemy's SQLite dialect drops tzinfo *without converting*
    (recorded as a runtime-proven fact in the local-timezone design doc), so an
    aware `2026-09-01T12:00+14:00` validated as the instant it really is would
    then be stored as the wall-clock `2026-09-01 12:00` — a day past the bound
    that just admitted it. Converting first means the value checked and the
    value stored are the same one.

    The app's own client already submits UTC (`soldAtFromDateInput` anchors the
    picked day at noon Z), so this changes nothing for it. When
    `backend/timeutils.py` lands from
    `docs/superpowers/plans/2026-08-22-local-timezone.md`, this becomes a call
    to its `utc_naive()`.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def reject_future_sold_at(value: datetime) -> datetime:
    """Normalized `value`, or raise `ValueError` if it is dated ahead of now.

    Shared with the CSV importer, which reaches `sold_at` by a different route
    (a parsed `Date Sold` column) and would otherwise let through exactly what
    the picker no longer can.
    """
    value = normalize_sold_at(value)
    if value > datetime.utcnow() + SOLD_AT_MAX_SKEW:
        raise ValueError("sold_at cannot be in the future")
    return value


# --- Auth ---
class LoginRequest(BaseModel):
    password: str
    # Optional so single-user (owner-only) setups can leave it blank.
    username: Optional[str] = None


class TokenResponse(BaseModel):
    token: str
    username: str


# --- Cards ---
class CardBase(BaseModel):
    player_name: str = ""
    year: Optional[int] = None
    brand: str = ""
    set_name: str = ""
    card_number: str = ""
    team: str = ""
    is_rookie: bool = False
    is_first_bowman: bool = False
    is_autograph: bool = False
    is_patch: bool = False
    is_refractor: bool = False
    parallel_color: Optional[str] = None
    serial_number: Optional[str] = None
    condition: str = "NM"
    quantity: int = Field(default=1, ge=1)
    # Same floor as `listed_price`: the two are the same kind of value, read by
    # the same consumers (the Sheets price column, the listing text, the
    # inventory value tile), and only one of them used to be guarded.
    suggested_price: Optional[float] = Field(default=None, ge=0)
    listed_price: Optional[float] = Field(default=None, ge=0)
    image_path: str = ""
    back_image_path: Optional[str] = None
    notes: Optional[str] = None


class CardCreate(CardBase):
    # Ties the save back to the scan that produced it, for correction capture.
    scan_id: Optional[int] = None


class CardUpdate(BaseModel):
    # Every field optional so the user can patch any subset
    player_name: Optional[str] = None
    year: Optional[int] = None
    brand: Optional[str] = None
    set_name: Optional[str] = None
    card_number: Optional[str] = None
    team: Optional[str] = None
    is_rookie: Optional[bool] = None
    is_first_bowman: Optional[bool] = None
    is_autograph: Optional[bool] = None
    is_patch: Optional[bool] = None
    is_refractor: Optional[bool] = None
    parallel_color: Optional[str] = None
    serial_number: Optional[str] = None
    condition: Optional[str] = None
    quantity: Optional[int] = Field(default=None, ge=1)
    suggested_price: Optional[float] = Field(default=None, ge=0)
    listed_price: Optional[float] = Field(default=None, ge=0)
    image_path: Optional[str] = None
    back_image_path: Optional[str] = None
    notes: Optional[str] = None


class CardOut(CardBase):
    model_config = ConfigDict(from_attributes=True)
    # Reads report what is stored; only writes are bounded. FastAPI validates
    # responses too, so inheriting the `ge=0` floors would turn a single legacy
    # row saved before the floor existed into a 500 on `GET /api/cards` — the
    # whole inventory unreadable because one price is wrong. Widening the input
    # bound is the wrong lever there, so the two are stated separately.
    suggested_price: Optional[float] = None
    listed_price: Optional[float] = None
    id: int
    status: str
    ebay_listing_id: Optional[str] = None
    ebay_listing_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    sold_at: Optional[datetime] = None
    sold_price: Optional[float] = None
    sheets_row: Optional[int] = None


# --- Duplicate check ---
class DuplicateCheckRequest(BaseModel):
    player_name: str = ""
    year: Optional[int] = None
    brand: str = ""
    set_name: str = ""
    card_number: str = ""
    parallel_color: Optional[str] = None
    serial_number: Optional[str] = None
    is_autograph: bool = False
    is_patch: bool = False
    is_refractor: bool = False
    is_first_bowman: bool = False


class DuplicateCheckResponse(BaseModel):
    duplicate: Optional[CardOut] = None


# --- Scan ---
class ScanResponse(BaseModel):
    image_path: str
    back_image_path: Optional[str] = None
    extracted: dict
    mock: bool = False
    # Set when a real extraction was attempted but failed (distinct from mock mode).
    error: Optional[str] = None
    scan_id: Optional[int] = None


# --- Pricing ---
class PricingRequest(BaseModel):
    player_name: str
    year: Optional[int] = None
    brand: Optional[str] = None
    set_name: Optional[str] = None
    card_number: Optional[str] = None


class PricingResponse(BaseModel):
    comps: List[dict]
    suggested_price: Optional[float] = None
    source: str
    note: Optional[str] = None


# --- eBay ---
class EbayListingUpdate(BaseModel):
    ebay_listing_id: str
    ebay_listing_url: str

    @field_validator("ebay_listing_url")
    @classmethod
    def _require_https(cls, v: str) -> str:
        # The URL is rendered as a clickable link in the inventory table (and
        # mirrored to Sheets), so reject anything that isn't plain https —
        # keeps javascript:/http: values out of the href.
        v = v.strip()
        if not v.lower().startswith("https://"):
            raise ValueError("ebay_listing_url must start with https://")
        return v


# --- Mark sold ---
class MarkSoldRequest(BaseModel):
    sold_price: float = Field(gt=0)
    sold_at: Optional[datetime] = None

    @field_validator("sold_at")
    @classmethod
    def _not_in_the_future(cls, v: Optional[datetime]) -> Optional[datetime]:
        # A mistyped year is accepted silently today and is permanent furniture
        # once accepted: it appears in the sold-years picker forever, sorts to
        # the end of every tax export, and the only way back is unmark-sold and
        # redo. Nothing else bounds this field — `sold_price > 0` was the only
        # validation on the request.
        if v is None:
            return None
        return reject_future_sold_at(v)


# --- Analytics / cost split ---
class UsageRow(BaseModel):
    username: str
    scans: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class ModelRow(BaseModel):
    model: str
    scans: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class DayRow(BaseModel):
    date: str              # "YYYY-MM-DD"
    scans: int
    est_cost_usd: float


class AnalyticsTotals(BaseModel):
    scans: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float
    corrections: int = 0


class AnalyticsReport(BaseModel):
    range: str                         # today | 7d | 30d | month | all
    since: Optional[datetime] = None   # None for all-time
    until: datetime
    totals: AnalyticsTotals
    by_user: List[UsageRow]
    by_model: List[ModelRow]
    by_day: List[DayRow]
    users: List[str]                   # distinct values for filter dropdowns
    models: List[str]


class ReassignRequest(BaseModel):
    from_user: str
    to_user: str
