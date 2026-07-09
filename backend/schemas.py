"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


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
    is_autograph: bool = False
    is_patch: bool = False
    is_refractor: bool = False
    parallel_color: Optional[str] = None
    serial_number: Optional[str] = None
    condition: str = "NM"
    quantity: int = 1
    suggested_price: Optional[float] = None
    listed_price: Optional[float] = None
    image_path: str = ""
    back_image_path: Optional[str] = None
    notes: Optional[str] = None


class CardCreate(CardBase):
    pass


class CardUpdate(BaseModel):
    # Every field optional so the user can patch any subset
    player_name: Optional[str] = None
    year: Optional[int] = None
    brand: Optional[str] = None
    set_name: Optional[str] = None
    card_number: Optional[str] = None
    team: Optional[str] = None
    is_rookie: Optional[bool] = None
    is_autograph: Optional[bool] = None
    is_patch: Optional[bool] = None
    is_refractor: Optional[bool] = None
    parallel_color: Optional[str] = None
    serial_number: Optional[str] = None
    condition: Optional[str] = None
    quantity: Optional[int] = None
    suggested_price: Optional[float] = None
    listed_price: Optional[float] = None
    image_path: Optional[str] = None
    back_image_path: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


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


# --- Scan ---
class ScanResponse(BaseModel):
    image_path: str
    back_image_path: Optional[str] = None
    extracted: dict
    mock: bool = False
    # Set when a real extraction was attempted but failed (distinct from mock mode).
    error: Optional[str] = None


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


# --- Mark sold ---
class MarkSoldRequest(BaseModel):
    sold_price: float
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
