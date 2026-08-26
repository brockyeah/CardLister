// Client mirror of backend/services/card_fields.py. The backend is the source
// of truth; this exists so the review form can offer the canonical grades as a
// dropdown instead of a free-text box that fragments the data. The shared case
// table (backend/tests/fixtures/condition_cases.json) is read by both suites —
// if condition.test.js fails, this mirror drifted, not the backend.

// Best to worst, ungraded first — the order the <select> renders.
export const CONDITION_VALUES = ['RAW', 'GEM-MT', 'NM-MT', 'NM', 'EX', 'VG', 'POOR']

export const CONDITION_LABELS = {
  RAW: 'RAW — ungraded',
  'GEM-MT': 'GEM-MT — gem mint',
  'NM-MT': 'NM-MT — near mint to mint',
  NM: 'NM — near mint',
  EX: 'EX — excellent',
  VG: 'VG — very good',
  POOR: 'POOR',
}

// Recognized spelling (case-folded, whitespace-collapsed) -> canonical value.
// Every canonical value maps to itself so the fold is idempotent; the form
// applies it on every render.
const VARIANTS = {
  RAW: 'RAW',
  UNGRADED: 'RAW',
  'UN-GRADED': 'RAW',

  'GEM-MT': 'GEM-MT',
  'GEM MT': 'GEM-MT',
  GEMMT: 'GEM-MT',
  'GEM MINT': 'GEM-MT',
  'GEM-MINT': 'GEM-MT',
  'GEM MINT 10': 'GEM-MT',
  'GEM MT 10': 'GEM-MT',

  'NM-MT': 'NM-MT',
  'NM MT': 'NM-MT',
  NMMT: 'NM-MT',
  'NM/MT': 'NM-MT',
  'NM-M': 'NM-MT',
  'NEAR MINT-MINT': 'NM-MT',
  'NEAR MINT MINT': 'NM-MT',
  'NEAR MINT TO MINT': 'NM-MT',

  NM: 'NM',
  'NEAR MINT': 'NM',
  'NEAR-MINT': 'NM',
  NRMT: 'NM',
  'NR MT': 'NM',

  EX: 'EX',
  EXCELLENT: 'EX',
  EXC: 'EX',

  VG: 'VG',
  'VERY GOOD': 'VG',
  'VERY-GOOD': 'VG',
  VGOOD: 'VG',

  POOR: 'POOR',
}

/**
 * Fold a recognized spelling of a grade to its canonical value.
 *
 * Anything unrecognized — an unknown code like "LP", a slab grade like
 * "PSA 10", a formula-escaped "-NM", a non-string — is returned **unchanged**.
 * The function can tidy a spelling it knows and can never invent, trim, or
 * reinterpret one it doesn't.
 */
export function normalizeCondition(value) {
  if (typeof value !== 'string') return value
  // Object.create(null) isn't used for VARIANTS, so guard the prototype chain:
  // normalizeCondition('constructor') must not return Object's constructor.
  const key = value.toUpperCase().split(/\s+/).filter(Boolean).join(' ')
  return Object.prototype.hasOwnProperty.call(VARIANTS, key) ? VARIANTS[key] : value
}

/**
 * The option list for the dropdown, given whatever the card currently holds.
 *
 * An unrecognized value is appended as its own option rather than dropped —
 * otherwise a `<select>` with no matching option renders as the first grade in
 * the list and would silently rewrite the card's condition on the next save.
 * A blank value gets a blank option for the same reason.
 */
export function conditionOptions(current) {
  const value = typeof current === 'string' ? current : ''
  if (value === '') return ['', ...CONDITION_VALUES]
  if (CONDITION_VALUES.includes(value)) return CONDITION_VALUES
  return [...CONDITION_VALUES, value]
}

/** Label for an option; unrecognized values are shown verbatim. */
export function conditionLabel(value) {
  if (value === '') return '— not set —'
  return CONDITION_LABELS[value] ?? value
}
