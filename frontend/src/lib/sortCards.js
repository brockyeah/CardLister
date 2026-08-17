// Sorting and search helpers for the Inventory table.

// Fields the free-text search box matches against.
const SEARCH_FIELDS = [
  'player_name', 'team', 'brand', 'set_name', 'card_number',
  'parallel_color', 'notes', 'year',
]

export function cardMatchesSearch(card, query) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return SEARCH_FIELDS.some((f) => {
    const v = card[f]
    return v != null && String(v).toLowerCase().includes(q)
  })
}

// The exact set of rows the table shows, given the status dropdown and the
// search box. Extracted from Inventory.jsx so the summary tiles and the table
// can be driven from one definition of "visible" — the tiles used to describe
// every card while the table below showed a subset.
export function filterCards(cards, { status = '', search = '' } = {}) {
  const list = Array.isArray(cards) ? cards : []
  return list.filter((c) => {
    if (status && c.status !== status) return false
    return cardMatchesSearch(c, search)
  })
}

// Whether the filters actually narrow anything — a blank search box and "All
// statuses" leave the tiles describing the whole collection, so there is
// nothing to caption.
export function isNarrowed({ status = '', search = '' } = {}) {
  return Boolean(status || search.trim())
}

// Stable sort with nulls/blanks always last regardless of direction.
// Strings compare case-insensitively and numerically ("BCP-9" < "BCP-100").
export function sortCards(cards, key, dir) {
  const mul = dir === 'asc' ? 1 : -1
  return [...cards].sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    const aEmpty = av == null || av === ''
    const bEmpty = bv == null || bv === ''
    if (aEmpty && bEmpty) return 0
    if (aEmpty) return 1
    if (bEmpty) return -1
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * mul
    return String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' }) * mul
  })
}
