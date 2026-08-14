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
// quantity would invent money that was never received.

// Missing/invalid quantity means one copy — matches the server default and the
// `c.quantity ?? 1` render in CardTable.
export function cardQuantity(card) {
  const q = Number(card?.quantity)
  return Number.isFinite(q) && q > 0 ? Math.floor(q) : 1
}

function sumQuantity(cards) {
  return cards.reduce((sum, c) => sum + cardQuantity(c), 0)
}

export function computeInventoryStats(cards) {
  const list = Array.isArray(cards) ? cards : []
  const active = list.filter((c) => c.status === 'active')
  return {
    total: sumQuantity(list),
    listed: sumQuantity(active),
    sold: sumQuantity(list.filter((c) => c.status === 'sold')),
    revenue: list.reduce((sum, c) => sum + (Number(c.sold_price) || 0), 0),
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
