"""SQLAlchemy ORM models."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from .database import Base


class Card(Base):
    __tablename__ = "cards"

    id = Column(Integer, primary_key=True, index=True)

    # Card identity
    player_name = Column(String, index=True, nullable=False, default="")
    year = Column(Integer, nullable=True)
    brand = Column(String, default="")
    set_name = Column(String, default="")
    card_number = Column(String, default="")
    team = Column(String, default="")

    # Flags
    is_rookie = Column(Boolean, default=False)
    is_autograph = Column(Boolean, default=False)
    is_patch = Column(Boolean, default=False)
    is_refractor = Column(Boolean, default=False)

    # Parallel / numbering
    parallel_color = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)

    # Condition + pricing
    condition = Column(String, default="NM")
    suggested_price = Column(Float, nullable=True)
    listed_price = Column(Float, nullable=True)

    # eBay linkage (filled in after the user publishes the listing)
    ebay_listing_id = Column(String, nullable=True)
    ebay_listing_url = Column(String, nullable=True)

    # Lifecycle
    status = Column(String, default="unlisted", index=True)  # unlisted | active | sold
    image_path = Column(String, default="")
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    sold_at = Column(DateTime, nullable=True)
    sold_price = Column(Float, nullable=True)

    # Row index in the synced Google Sheet (so we can update in place)
    sheets_row = Column(Integer, nullable=True)


class UsageEvent(Base):
    """One row per billable Anthropic call, attributed to a user.

    Used to split shared API costs: aggregate by username over a period and
    price the tokens. New table, so create_all picks it up with no migration.
    """
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True, nullable=False, default="")
    kind = Column(String, default="scan")  # what triggered the call
    model = Column(String, default="")
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
