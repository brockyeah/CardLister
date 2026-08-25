// eBay final-value fee and net-proceeds estimate.
//
// Every price this app shows is gross: the comps median, the "Listed at"
// tile, the sale price typed into Mark as Sold. eBay takes a percentage plus
// a flat per-order charge off the top, so a $10 card is really ~$8.37 in
// hand — and the gap is proportionally worst on the cheap cards that make up
// most of a raw-card inventory, where the flat per-order fee alone is ~3% of
// the sale. Deciding a list price against a gross number is deciding it
// against a number nobody receives.
//
// This is deliberately an *estimate* and says so wherever it renders:
//   - eBay charges the final value fee on the total the buyer pays, which
//     includes shipping and (where applicable) tax. Only the item price is
//     known here, so real proceeds are a little lower than this figure.
//   - Promoted-listing fees, international-transaction fees and store
//     subscriptions all move the number and none of them are modeled.
//   - eBay's standing 50%-off promotion on singles at $1,000+ is deliberately
//     NOT modeled: it is a promotion, not the schedule, and an estimate that
//     errs optimistic is worse than useless on a pricing decision.
// It is a sanity check on a listing decision, not accounting.

// eBay's Sports Trading Cards schedule for a seller with no store or a
// Starter store (verified 2026-08-25). Both parts are tiered, and both
// thresholds bite in this inventory's normal range — a flat
// "rate x price + $0.30" understates the fee on every card over $10:
//   - 13.25% on the sale up to $7,500, 2.35% on the portion above it.
//   - $0.30 per order at or under $10, $0.40 per order above it.
export const DEFAULT_FEE_SCHEDULE = {
  rate: 0.1325,
  rateAbove: 0.0235,
  tier: 7500,
  fixed: 0.3,
  fixedAbove: 0.4,
  fixedThreshold: 10,
}

/**
 * A build-time override, validated. Returns `fallback` for anything missing
 * or nonsensical rather than rendering a fee computed from garbage.
 *
 * A rate is a **fraction** (0.1325), not a percentage (13.25) — the two are
 * indistinguishable at a glance and only one of them is right, so a value at
 * or above `max` is treated as the mistake it almost certainly is instead of
 * being applied. Exported for its own test; the schedule below calls it once
 * per field at import.
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
export const FEE_SCHEDULE = {
  rate: parseFeeOverride(env.VITE_EBAY_FEE_RATE, DEFAULT_FEE_SCHEDULE.rate, { max: 1 }),
  rateAbove: parseFeeOverride(env.VITE_EBAY_FEE_RATE_ABOVE, DEFAULT_FEE_SCHEDULE.rateAbove, { max: 1 }),
  tier: parseFeeOverride(env.VITE_EBAY_FEE_TIER, DEFAULT_FEE_SCHEDULE.tier),
  fixed: parseFeeOverride(env.VITE_EBAY_FEE_FIXED, DEFAULT_FEE_SCHEDULE.fixed),
  fixedAbove: parseFeeOverride(env.VITE_EBAY_FEE_FIXED_ABOVE, DEFAULT_FEE_SCHEDULE.fixedAbove),
  fixedThreshold: parseFeeOverride(env.VITE_EBAY_FEE_FIXED_THRESHOLD, DEFAULT_FEE_SCHEDULE.fixedThreshold),
}

/** Round to whole cents, the unit both the fee and the payout are settled in. */
function toCents(n) {
  return Math.round(n * 100) / 100
}

/**
 * `{ fee, net }` for a sale at `price`, or null when there is no price to
 * estimate from.
 *
 * The percentage is applied per tier, not as one rate chosen by the total:
 * a $10,000 card pays 13.25% on the first $7,500 and 2.35% only on the
 * remaining $2,500. Charging the low rate on the whole sale would understate
 * the fee by hundreds of dollars on exactly the card where the number
 * matters most.
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
export function estimateFees(price, schedule = FEE_SCHEDULE) {
  const n = Number(price)
  if (!Number.isFinite(n) || n <= 0) return null
  const { rate, rateAbove, tier, fixed, fixedAbove, fixedThreshold } = schedule
  const percent = n <= tier ? n * rate : tier * rate + (n - tier) * rateAbove
  const perOrder = n > fixedThreshold ? fixedAbove : fixed
  const fee = toCents(percent + perOrder)
  return { fee, net: toCents(n - fee) }
}

/**
 * Estimated net as money, or the same em dash the comps list uses.
 *
 * A loss reads `-$0.21`, not `$-0.21`: the sign belongs in front of the
 * amount, and the misplaced version is easy to skim straight past on the one
 * figure that most needs to be noticed.
 */
export function formatNet(price, schedule = FEE_SCHEDULE) {
  const estimate = estimateFees(price, schedule)
  if (!estimate) return '—'
  const { net } = estimate
  return net < 0 ? `-$${Math.abs(net).toFixed(2)}` : `$${net.toFixed(2)}`
}

/** A rate as a percentage with no float noise: 0.1325 -> "13.25%". */
function percent(rate) {
  return `${Number((rate * 100).toFixed(4))}%`
}

/**
 * Money for prose: 7500 -> "$7,500", 0.4 -> "$0.40".
 *
 * Cents get both digits — "$0.4" reads as a typo in a sentence about fees —
 * while a whole-dollar threshold keeps its bare form rather than becoming
 * "$7,500.00", which invites reading it as a precise amount.
 */
function money(n) {
  const digits = Number.isInteger(n) ? 0 : 2
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`
}

/**
 * The schedule the figures were computed from, in words — so a net on screen
 * can be checked against the rates that produced it rather than taken on
 * faith, and so a stale rate is visible the day eBay changes one.
 *
 * Written for the whole schedule rather than for one price: the Comps modal
 * shows two nets at once, and they can straddle the per-order threshold.
 */
export function formatFeeSchedule(schedule = FEE_SCHEDULE) {
  const { rate, rateAbove, tier, fixed, fixedAbove, fixedThreshold } = schedule
  return (
    `${percent(rate)} of the sale (${percent(rateAbove)} above ${money(tier)}) ` +
    `plus ${money(fixedAbove)} per order over ${money(fixedThreshold)}, ${money(fixed)} at or under.`
  )
}

/**
 * What the estimate leaves out. Shown with every net figure.
 *
 * Names both other components of eBay's fee base, not just shipping: the fee
 * is charged on the total the buyer pays, which includes the sales tax eBay
 * collects and remits — money the seller never receives but is charged a
 * percentage of. Every omission here pushes the real payout *below* this
 * estimate, so the disclosure has to be complete or the figure reads as a
 * floor when it is a ceiling.
 */
export const FEE_CAVEAT =
  'Estimate on the item price only — eBay also charges the fee on the shipping and sales tax ' +
  'the buyer pays, and promoted-listing fees are not included.'

/** The full note rendered beneath a net: the schedule, then the caveat. */
export function feeDisclaimer(schedule = FEE_SCHEDULE) {
  return `${formatFeeSchedule(schedule)} ${FEE_CAVEAT}`
}
