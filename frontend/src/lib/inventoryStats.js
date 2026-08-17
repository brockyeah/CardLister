// Inventory summary tiles.
//
// A row is not a card: `quantity` is how many physical copies that row stands
// for. Counting rows understated a collection with any duplicate-merged rows
// (the save-time "increase count" flow makes those routinely), and valuing a
// qty-3 row at one `listed_price` understated Est. Active Value the same way.
// So the counts and the active value are all per-copy.
//
// Revenue stays per-row on purpose: `sold_price` is the amount a sale actually
// brought in, recorded once when the row was marked sold. Multiplying it by
// quantity would invent money that was never received. It is also filtered to
// sold rows — the CSV importer fills sold_price from the "Sale Price" column
// whatever the row's status (routers/cards.py), so an imported active row can
// carry one, and counting it would report revenue from a card still on hand.

// Missing/invalid quantity means one copy — matches the server default and the
// `c.quantity ?? 1` render in CardTable. The floor is clamped to 1 so a
// positive fraction can't round down to zero copies and erase a real card.
export function cardQuantity(card) {
  const q = Number(card?.quantity)
  return Number.isFinite(q) && q > 0 ? Math.max(1, Math.floor(q)) : 1
}

function sumQuantity(cards) {
  return cards.reduce((sum, c) => sum + cardQuantity(c), 0)
}

// Caption for a tile whose value describes the *filtered* rows: the
// collection-wide number has to stay in view, or narrowing to "sold" leaves a
// tile that simply looks wrong with no way to tell it apart from a data bug.
// Returns null when the two agree so an unfiltered view stays uncluttered.
export function overallHint(value, overallValue, format = String) {
  if (value === overallValue) return null
  return `of ${format(overallValue)} overall`
}

// Rows vs copies: only differs once something was quantity-merged.
export function copiesHint(stats) {
  if (!stats || stats.total === stats.rowCount) return null
  return `${stats.rowCount} ${stats.rowCount === 1 ? 'row' : 'rows'}`
}

// Tile captions are built from several independent facts (rows-vs-copies, the
// overall total); drop the ones that don't apply and join what's left.
export function joinHints(...parts) {
  return parts.filter(Boolean).join(' · ') || null
}

// Badge next to the heading whenever a filter is active, so a tile reading $0
// is legible as "nothing matched" rather than "the data is gone".
export function filteredScopeLabel(rowCount) {
  if (!rowCount) return 'No rows match this filter — totals are zero'
  return `Totals cover ${rowCount} matching ${rowCount === 1 ? 'row' : 'rows'}`
}

export function computeInventoryStats(cards) {
  const list = Array.isArray(cards) ? cards : []
  const active = list.filter((c) => c.status === 'active')
  const sold = list.filter((c) => c.status === 'sold')
  return {
    total: sumQuantity(list),
    listed: sumQuantity(active),
    sold: sumQuantity(sold),
    revenue: sold.reduce((sum, c) => sum + (Number(c.sold_price) || 0), 0),
    activeValue: active.reduce(
      (sum, c) => sum + (Number(c.listed_price) || 0) * cardQuantity(c),
      0,
    ),
    // Rows vs copies differ only when something was merged; the UI uses this
    // to caption the tiles instead of silently showing a different number
    // than the table's row count.
    rowCount: list.length,
  }
}
