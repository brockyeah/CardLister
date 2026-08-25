// eBay final-value fee and net-proceeds estimate.
//
// Every price this app shows is gross: the comps median, the "Listed at"
// tile, the sale price typed into Mark as Sold. eBay takes a percentage plus
// a flat per-order charge off the top, so a $10 card is really ~$8.37 in
// hand — and the gap is proportionally worst on the cheap cards that make up
// most of a raw-card inventory, where the flat $0.30 alone is 3% of the sale.
// Deciding a list price against a gross number is deciding it against a
// number nobody receives.
//
// This is deliberately an *estimate* and says so wherever it renders:
//   - eBay charges the final value fee on the total the buyer pays, which
//     includes shipping and (where applicable) tax. Only the item price is
//     known here, so real proceeds are a little lower than this figure.
//   - Promoted-listing fees, international-transaction fees and store
//     subscriptions all move the number and none of them are modeled.
// It is a sanity check on a listing decision, not accounting.

// eBay's Sports Trading Cards final value fee at the time of writing:
// 13.25% of the sale total plus $0.30 per order.
export const DEFAULT_FEE_RATE = 0.1325
export const DEFAULT_FEE_FIXED = 0.3

/**
 * A build-time override, validated. Returns `fallback` for anything missing
 * or nonsensical rather than rendering a fee computed from garbage.
 *
 * The rate is a **fraction** (0.1325), not a percentage (13.25) — the two are
 * indistinguishable at a glance and only one of them is right, so a value at
 * or above `max` is treated as the mistake it almost certainly is instead of
 * being applied. Exported for its own test; the module constants below call
 * it once at import.
 */
export function parseFeeOverride(raw, fallback, { max = Infinity } = {}) {
  if (raw === undefined || raw === null || raw === '') return fallback
  const n = Number(raw)
  if (!Number.isFinite(n) || n < 0 || n >= max) {
    // Visible in the console rather than silent: a misconfigured rate that
    // falls back looks exactly like one that applied.
    if (typeof console !== 'undefined') {
      console.warn(`Ignoring invalid eBay fee override ${JSON.stringify(raw)}; using ${fallback}.`)
    }
    return fallback
  }
  return n
}

// Vite inlines these at build time. The production Dockerfile passes no build
// args, so a deploy uses the defaults above; the override exists for local and
// self-hosted builds, and wiring it through the image is a backlog item.
const env = typeof import.meta !== 'undefined' ? (import.meta.env || {}) : {}
export const FEE_RATE = parseFeeOverride(env.VITE_EBAY_FEE_RATE, DEFAULT_FEE_RATE, { max: 1 })
export const FEE_FIXED = parseFeeOverride(env.VITE_EBAY_FEE_FIXED, DEFAULT_FEE_FIXED)

/** Round to whole cents, the unit both the fee and the payout are settled in. */
function toCents(n) {
  return Math.round(n * 100) / 100
}

/**
 * `{ fee, net }` for a sale at `price`, or null when there is no price to
 * estimate from.
 *
 * Unusable input returns null instead of a number, for the reason
 * `formatCompPrice` gives: `Number(null).toFixed(2)` is `$0.00`, a
 * plausible-looking figure that is simply wrong, and this one would sit
 * beside a real price where the difference is invisible.
 *
 * A negative net is returned as-is. Below about $0.35 the flat fee exceeds
 * the sale and the seller genuinely loses money on the order; rounding that
 * up to zero would hide the one case where the estimate has something urgent
 * to say.
 */
export function estimateFees(price, rate = FEE_RATE, fixed = FEE_FIXED) {
  const n = Number(price)
  if (!Number.isFinite(n) || n <= 0) return null
  const fee = toCents(n * rate + fixed)
  return { fee, net: toCents(n - fee) }
}

/**
 * Estimated net as money, or the same em dash the comps list uses.
 *
 * A loss reads `-$0.21`, not `$-0.21`: the sign belongs in front of the
 * amount, and the misplaced version is easy to skim straight past on the one
 * figure that most needs to be noticed.
 */
export function formatNet(price, rate = FEE_RATE, fixed = FEE_FIXED) {
  const estimate = estimateFees(price, rate, fixed)
  if (!estimate) return '—'
  const { net } = estimate
  return net < 0 ? `-$${Math.abs(net).toFixed(2)}` : `$${net.toFixed(2)}`
}

/**
 * "13.25% + $0.30" — the basis, so the number on screen can be checked
 * against the rate that produced it instead of being taken on faith.
 */
export function formatFeeBasis(rate = FEE_RATE, fixed = FEE_FIXED) {
  const pct = Number((rate * 100).toFixed(2))
  return `${pct}% + $${fixed.toFixed(2)}`
}

/** The caveat shown with any net figure. Item price only — see the header. */
export const FEE_DISCLAIMER =
  'Estimate on the item price only — eBay also charges the fee on shipping the buyer pays, ' +
  'and promoted-listing fees are not included.'
