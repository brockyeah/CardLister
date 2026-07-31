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
