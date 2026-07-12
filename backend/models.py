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
    is_first_bowman = Column(Boolean, default=False)  # printed "1st" logo (Bowman prospects)
    is_autograph = Column(Boolean, default=False)
    is_patch = Column(Boolean, default=False)
    is_refractor = Column(Boolean, default=False)

    # Parallel / numbering
    parallel_color = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)

    # Condition + pricing
    condition = Column(String, default="NM")
    quantity = Column(Integer, nullable=False, default=1, server_default="1")
    suggested_price = Column(Float, nullable=True)
    listed_price = Column(Float, nullable=True)

    # eBay linkage (filled in after the user publishes the listing)
    ebay_listing_id = Column(String, nullable=True)
    ebay_listing_url = Column(String, nullable=True)

    # Lifecycle
    status = Column(String, default="unlisted", index=True)  # unlisted | active | sold
    image_path = Column(String, default="")
    back_image_path = Column(String, nullable=True)
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


class Scan(Base):
    """One row per real (non-mock) vision extraction — the raw model output as
    shown to the user, kept so we can diff it against what they actually save."""
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True, nullable=False, default="")
    image_path = Column(String, default="")
    back_image_path = Column(String, nullable=True)
    model = Column(String, default="")
    extracted_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Correction(Base):
    """A user's fix to a scan: what the model said vs. what got saved. Feeds the
    cheat-sheet prompt injection and the exact-card identity override."""
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, index=True, nullable=True)
    card_id = Column(Integer, index=True, nullable=True)
    username = Column(String, index=True, nullable=False, default="")
    # Corrected identity, denormalized for exact-card matching
    year = Column(Integer, nullable=True)
    brand = Column(String, default="")
    set_name = Column(String, default="")
    card_number = Column(String, default="")
    extracted_json = Column(Text, default="{}")
    corrected_json = Column(Text, default="{}")
    diff_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CallupEvent(Base):
    """One MLB roster transaction we care about (a call-up). Doubles as the
    dedup ledger (unique tx_id) and the data behind the news ticker."""
    __tablename__ = "callup_events"

    id = Column(Integer, primary_key=True, index=True)
    tx_id = Column(Integer, unique=True, index=True, nullable=False)  # MLB transaction id
    date = Column(String, default="")           # YYYY-MM-DD
    type_desc = Column(String, default="")      # "Selected" | "Recalled"
    player_name = Column(String, default="")
    person_id = Column(Integer, nullable=True)
    to_team = Column(String, default="")
    description = Column(Text, default="")
    inventory_match = Column(Boolean, default=False)
    matched_card_count = Column(Integer, default=0)
    first_bowman_count = Column(Integer, default=0)  # of the matches, how many are 1st Bowmans
    emailed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
