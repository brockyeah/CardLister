/**
 * A confirmation prompt at the moment of a fat-fingered sale price.
 *
 * `MarkSoldRequest` validates only `sold_price > 0`, so a mistyped `2500` for
 * a `$25` card is stored as ordinary and mirrored to the tax export, and the
 * only way back is unmark-sold and redo. A hard upper bound is the wrong tool
 * — cards genuinely sell for five figures, so any cap refuses a real sale —
 * but the modal already knows the card's listed price and can ask: confirm
 * once when the entered price is more than ~20× or under ~1/20th of what the
 * seller advertised. Same shape as the duplicate-detection confirm and the
 * bulk-orphan warning: a question at the moment of the mistake, not a refusal.
 *
 * A card with no listed price has nothing to compare against — the seller may
 * have gone straight from scan to sold without a price step — so this returns
 * null there rather than warning against a phantom baseline. Same for a listed
 * price of zero, an entered price that is not a positive number, or a
 * pathological value that would divide by something un-comparable: the
 * function is only useful when both inputs describe a real price.
 *
 * The factor threshold matches what a phone keypad slip actually produces —
 * dropping or adding a digit is ~10×, and a whole extra order of magnitude
 * covers the two-digit slip while leaving room for legitimate re-pricing
 * (2× / 5× swings against a listed price are common, so they must not
 * trigger).
 */
const FACTOR = 20

export function flagImplausibleSalePrice(enteredPrice, listedPrice) {
  const entered = _positiveNumber(enteredPrice)
  const listed = _positiveNumber(listedPrice)
  if (entered == null || listed == null) return null
  if (entered >= listed * FACTOR) {
    return { kind: 'much_higher', factor: entered / listed }
  }
  if (listed >= entered * FACTOR) {
    return { kind: 'much_lower', factor: listed / entered }
  }
  return null
}

// Number(x) coerces truthy strings, empty strings, null and booleans in ways
// that would produce silent false-negatives here — the modal used to hand a
// bare `<input>` value straight in, and Number('  ') is 0. Guard the type
// first so only a real positive number survives.
function _positiveNumber(value) {
  const n = typeof value === 'string' ? Number(value) : value
  if (typeof n !== 'number' || !Number.isFinite(n) || n <= 0) return null
  return n
}

/** Human-readable prompt for the returned warning. Kept beside the flagger so
 * a rename of the `kind` values fails loud rather than silently rendering the
 * wrong sentence. */
export function salePriceConfirmMessage(warning, listedPrice) {
  if (!warning) return ''
  const listed = _positiveNumber(listedPrice)
  const listedStr = listed != null ? `$${listed.toFixed(2)}` : ''
  const times = Math.round(warning.factor)
  if (warning.kind === 'much_higher') {
    return `That's ~${times}× the listed price${listedStr ? ' of ' + listedStr : ''}. Confirm this is the actual sale price?`
  }
  return `That's ~1/${times} the listed price${listedStr ? ' of ' + listedStr : ''}. Confirm this is the actual sale price?`
}
