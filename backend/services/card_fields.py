"""Canonical values for free-text card fields.

Today this covers `condition` only. The column is a plain string that reaches
the DB from three places — the review form, vision extraction, and CSV import —
and nothing ever agreed on a spelling, so "NM", "nm ", and "Near Mint" all
accumulated as distinct values in the inventory, the Sheets "Condition" column,
and the sold-cards tax export.

The normalizer is deliberately conservative: it folds only spellings that
unambiguously name the *same* grade, and returns anything else untouched.
Mapping a value onto a different grade (say "Mint" onto NM-MT) would restate
what the seller is claiming about the card, and stripping punctuation would
break both the CSV formula-injection escape and the export/import round-trip.

`frontend/src/lib/condition.js` mirrors this module so the review form's
dropdown offers exactly the grades the importer folds to; the shared case table
in `backend/tests/fixtures/condition_cases.json` pins the two together.
"""

# Best to worst, with the ungraded case first — the order the dropdown renders.
CONDITION_VALUES = ["RAW", "GEM-MT", "NM-MT", "NM", "EX", "VG", "POOR"]

# Recognized spelling (already case-folded and whitespace-collapsed) -> canonical
# value. Every canonical value maps to itself, which is what makes the fold
# idempotent — the form applies it on every render.
_VARIANTS = {
    "RAW": "RAW",
    "UNGRADED": "RAW",
    "UN-GRADED": "RAW",

    "GEM-MT": "GEM-MT",
    "GEM MT": "GEM-MT",
    "GEMMT": "GEM-MT",
    "GEM MINT": "GEM-MT",
    "GEM-MINT": "GEM-MT",
    "GEM MINT 10": "GEM-MT",
    "GEM MT 10": "GEM-MT",

    "NM-MT": "NM-MT",
    "NM MT": "NM-MT",
    "NMMT": "NM-MT",
    "NM/MT": "NM-MT",
    "NM-M": "NM-MT",
    "NEAR MINT-MINT": "NM-MT",
    "NEAR MINT MINT": "NM-MT",
    "NEAR MINT TO MINT": "NM-MT",

    "NM": "NM",
    "NEAR MINT": "NM",
    "NEAR-MINT": "NM",
    "NRMT": "NM",
    "NR MT": "NM",

    "EX": "EX",
    "EXCELLENT": "EX",
    "EXC": "EX",

    "VG": "VG",
    "VERY GOOD": "VG",
    "VERY-GOOD": "VG",
    "VGOOD": "VG",

    "POOR": "POOR",
}


def normalize_condition(value):
    """Fold a recognized spelling of a grade to its canonical value.

    Anything not recognized — an unknown code like "LP", a slab grade like
    "PSA 10", a formula-escaped "-NM", a non-string — comes back **unchanged**.
    That is the whole safety property: the function can tidy a spelling it
    knows, and can never invent, trim, or reinterpret one it doesn't.
    """
    if not isinstance(value, str):
        return value
    # Case-fold and collapse whitespace runs (split() handles tabs and newlines
    # too) purely to build the lookup key — `value` itself is what gets returned
    # when there is no match, so nothing is silently trimmed.
    key = " ".join(value.upper().split())
    return _VARIANTS.get(key, value)
