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
    """Bounded plain-text digest of recent corrections for prompt injection.

    One rule per (context, field): rows arrive newest-first, so the first rule
    seen for a field in a set is the most recent correction and the only one
    taught. Deduping on the *rendered rule* instead — which is what this did —
    kept both halves of a reversed correction, because they render differently:
    fix "Chrome" → "Chrome Prospects" today and reverse it next week and every
    later scan carried a contradictory pair with nothing marking which one
    still stood. It also let one much-corrected field eat the 30-rule budget
    and crowd out every other lesson, and both effects got worse the longer the
    app was used.

    Collapsing a field to its newest correction is right for what this digest
    is *for*: the module docstring scopes it to naming and numbering
    conventions, which have one current answer per set. Per-card facts are the
    exact-match overlay's job (`find_exact_match`), not the cheat-sheet's.
    """
    rows = (
        db.query(Correction)
        # id breaks created_at ties so "newest wins" is deterministic rather
        # than left to SQLite's row order — same reason the Sheets resync
        # orders by (created_at, id).
        .order_by(Correction.created_at.desc(), Correction.id.desc())
        .limit(200)
        .all()
    )
    lines, seen = [], set()
    for row in rows:
        diff = json.loads(row.diff_json or "{}")
        context = " ".join(str(p) for p in (row.year, row.brand, row.set_name) if p) or "unknown set"
        for field, change in diff.items():
            key = (context, field)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                f"- {context}: you said {field}={change.get('from')!r}; "
                f"the user corrected it to {change.get('to')!r}."
            )
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
        # id tiebreaker for the same reason as build_cheatsheet: this returns
        # the *latest* correction for the card, and two rows sharing a
        # created_at would otherwise resolve in whatever order SQLite chose.
        .order_by(Correction.created_at.desc(), Correction.id.desc())
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
