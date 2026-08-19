// Comp-set shape, for the review form and the inventory Comps modal.
//
// The pricing chain returns up to 10 comps and a `suggested_price` that is
// their **median** (see the per-source modules under backend/services). A
// median is a single number, and on its own it cannot distinguish a comp set
// clustered at $8–$9 from one that runs $4, $6, $8, $70, $90 — yet the second
// is the case where the suggested price is least trustworthy, because it
// usually means parallels/serialled/graded copies got mixed into a base card's
// comps. That contamination is a known open problem, so until the comps
// themselves are filtered, the least the UI can do is say when the spread is
// wide enough that the number should not be taken at face value.
//
// Deliberately does NOT recompute a median. The server's `suggested_price` is
// the one the form fills in and the one "Set Price to $X" applies; deriving a
// second one here would eventually disagree with it (rounding, or a source
// that trims outliers) and leave two different numbers on screen with no way
// to tell which is real.

// A comp set whose top price is this many times its bottom price is flagged.
// 3× is well past normal condition/timing variance for the same card and
// reliably indicates a different *product* in the list.
export const WIDE_SPREAD_RATIO = 3

// Below this, a range is noise: two comps that happen to be $5 and $20 say
// nothing about the distribution, and flagging them trains the user to ignore
// the warning.
export const MIN_COMPS_FOR_SPREAD = 3

// A price is usable if it is a real, positive amount. Sources hand-build their
// comp dicts and nothing pins the shape, so a null or an unparseable string can
// reach here.
function isUsablePrice(n) {
  return Number.isFinite(n) && n > 0
}

function usablePrices(comps) {
  return (comps || [])
    .map((c) => Number(c?.price))
    .filter(isUsablePrice)
    .sort((a, b) => a - b)
}

/**
 * One comp's price as money, or a marker when it is not usable.
 *
 * Shares `isUsablePrice` with the summary on purpose. A bare
 * `Number(price).toFixed(2)` turns `null` into `$0.00` — a plausible-looking
 * price that is simply wrong — and an unparseable string into `$NaN`, while
 * the range and count above the list quietly exclude both. That leaves the
 * list and its own summary disagreeing with nothing to explain the gap.
 */
export function formatCompPrice(price) {
  const n = Number(price)
  return isUsablePrice(n) ? `$${n.toFixed(2)}` : '—'
}

/**
 * { count, low, high, wide } over the comps that carry a usable price, or null
 * when none do. `count` is the number actually summarized, which can be lower
 * than `comps.length` if a source emitted an unparseable price — the caption
 * should describe what it measured, not what it was handed.
 */
export function summarizeComps(comps) {
  const prices = usablePrices(comps)
  if (prices.length === 0) return null
  const low = prices[0]
  const high = prices[prices.length - 1]
  return {
    count: prices.length,
    low,
    high,
    wide: prices.length >= MIN_COMPS_FOR_SPREAD && high >= low * WIDE_SPREAD_RATIO,
  }
}

/** "$4.00 – $90.00", or a single price when every comp agrees. */
export function formatCompRange(summary) {
  if (!summary) return ''
  const money = (n) => `$${n.toFixed(2)}`
  return summary.low === summary.high
    ? money(summary.low)
    : `${money(summary.low)} – ${money(summary.high)}`
}

/**
 * The caution shown beside a wide comp set, or null when the spread is tight
 * enough that the suggested price stands on its own.
 */
export function spreadWarning(summary) {
  if (!summary?.wide) return null
  const factor = Math.round(summary.high / summary.low)
  return (
    `Comps range ${factor}× from low to high — the suggested price is a median, ` +
    `so parallels, serial-numbered or graded copies mixed into this list will pull it off. ` +
    `Check the titles below before trusting it.`
  )
}
