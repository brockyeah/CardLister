"""Learning-from-corrections: capture user fixes to scans, feed them back.

Two mechanisms (approved design):
- Cheat-sheet: a bounded digest of recent corrections appended to each scan
  prompt so the model learns this collection's naming/numbering conventions.
- Exact-match override: when the same card (brand + card number + year) was
  corrected before, overlay the corrected IDENTITY fields onto the extraction.

Copy-specific attributes are recorded (the cheat-sheet may reference them) but
are NEVER overridden — the same card number exists as base, refractor, gold /50…
"""
import json
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Correction, Scan

# Safe to overlay on an exact card match — facts tied to the card's identity.
IDENTITY_FIELDS = ["player_name", "year", "brand", "set_name", "card_number", "team", "is_rookie", "is_first_bowman"]
# Recorded in corrections but never overridden (vary per physical copy).
COPY_SPECIFIC_FIELDS = ["is_autograph", "is_patch", "is_refractor", "parallel_color", "serial_number"]
TRACKED_FIELDS = IDENTITY_FIELDS + COPY_SPECIFIC_FIELDS

CHEATSHEET_MAX_RULES = 30
CHEATSHEET_MAX_CHARS = 4000


def _norm(value):
    """Normalize for comparison: strings casefolded/stripped; ''/None equal."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().casefold()
    return value


def diff_correction(extracted: dict, saved: dict) -> dict:
    """{field: {"from": x, "to": y}} for tracked fields the user changed."""
    diff = {}
    for field in TRACKED_FIELDS:
        before, after = extracted.get(field), saved.get(field)
        if _norm(before) != _norm(after):
            diff[field] = {"from": before, "to": after}
    return diff


def record_correction(db: Session, scan: Scan, saved: dict, card_id, username) -> Optional[Correction]:
    """Diff the scan's extraction against the saved payload; store if non-empty."""
    extracted = json.loads(scan.extracted_json or "{}")
    diff = diff_correction(extracted, saved)
    if not diff:
        return None
    correction = Correction(
        scan_id=scan.id,
        card_id=card_id,
        username=username,
        year=saved.get("year"),
        brand=saved.get("brand") or "",
        set_name=saved.get("set_name") or "",
        card_number=saved.get("card_number") or "",
        extracted_json=json.dumps({f: extracted.get(f) for f in TRACKED_FIELDS}, default=str),
        corrected_json=json.dumps({f: saved.get(f) for f in TRACKED_FIELDS}, default=str),
        diff_json=json.dumps(diff, default=str),
    )
    db.add(correction)
    db.commit()
    return correction


def build_cheatsheet(db: Session) -> str:
    """Bounded plain-text digest of recent corrections for prompt injection."""
    rows = db.query(Correction).order_by(Correction.created_at.desc()).limit(200).all()
    lines, seen = [], set()
    for row in rows:
        diff = json.loads(row.diff_json or "{}")
        context = " ".join(str(p) for p in (row.year, row.brand, row.set_name) if p) or "unknown set"
        for field, change in diff.items():
            rule = f"- {context}: you said {field}={change.get('from')!r}; the user corrected it to {change.get('to')!r}."
            if rule in seen:
                continue
            seen.add(rule)
            lines.append(rule)
            if len(lines) >= CHEATSHEET_MAX_RULES:
                break
        if len(lines) >= CHEATSHEET_MAX_RULES:
            break
    return "\n".join(lines)[:CHEATSHEET_MAX_CHARS]


def find_exact_match(db: Session, extracted: dict) -> Optional[dict]:
    """Corrected IDENTITY fields from the latest correction of the same card
    (normalized brand + card number + year), or None."""
    card_number = _norm(extracted.get("card_number"))
    brand = _norm(extracted.get("brand"))
    year = extracted.get("year")
    if not card_number or not brand or not year:
        return None
    rows = (
        db.query(Correction)
        .filter(Correction.year == year)
        .order_by(Correction.created_at.desc())
        .limit(100)
        .all()
    )
    for row in rows:
        if _norm(row.brand) == brand and _norm(row.card_number) == card_number:
            corrected = json.loads(row.corrected_json or "{}")
            return {f: corrected.get(f) for f in IDENTITY_FIELDS if corrected.get(f) not in (None, "")}
    return None


def apply_exact_match(db: Session, extracted: dict) -> dict:
    """Overlay identity fields from a past correction of the same card, if any."""
    overlay = find_exact_match(db, extracted)
    if not overlay:
        return extracted
    merged = {**extracted, **overlay}
    note = "Applied your saved corrections for this exact card (identity fields only)."
    existing = merged.get("confidence_notes") or ""
    merged["confidence_notes"] = f"{existing} {note}".strip()
    return merged
