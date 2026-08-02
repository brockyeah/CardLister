"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    suggested_price: Optional[float] = None
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
    suggested_price: Optional[float] = None
    listed_price: Optional[float] = Field(default=None, ge=0)
    image_path: Optional[str] = None
    back_image_path: Optional[str] = None
    notes: Optional[str] = None


class CardOut(CardBase):
    model_config = ConfigDict(from_attributes=True)
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
    def _https_only(cls, v: str) -> str:
        # Rejects javascript:/data: URIs — the value round-trips straight into an
        # <a href> in the frontend with no further sanitization.
        if not v.lower().startswith(("http://", "https://")):
            raise ValueError("ebay_listing_url must start with http:// or https://")
        return v


# --- Mark sold ---
class MarkSoldRequest(BaseModel):
    sold_price: float = Field(gt=0)
    sold_at: Optional[datetime] = None


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
