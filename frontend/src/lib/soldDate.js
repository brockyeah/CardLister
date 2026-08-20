// Mark-sold works on a *calendar date* — the user picks a day in a `<input
// type="date">`, not an instant — so both ends of that round trip have to be
// expressed in the user's own day, not UTC's.
//
// Both halves were previously UTC:
//   `new Date().toISOString().slice(0, 10)` is the UTC date, so from 8pm EDT
//   onward the picker pre-filled *tomorrow* and an evening sale was stamped a
//   day late unless the user noticed.
//   `new Date('2026-08-20').toISOString()` parses a bare YYYY-MM-DD as UTC
//   midnight per spec, which is the *previous* day anywhere west of UTC.
//
// Sold dates feed the Sheets "Date Sold" column, the tax-year CSV export and
// days-to-sell analytics, so a date off by one propagates — and a sale that
// slides across a New Year boundary lands in the wrong tax return.

/** Today's date as YYYY-MM-DD in the *local* zone (what the user calls today). */
export function todayLocalDate(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/**
 * Turn a `<input type="date">` value into the instant to send as `sold_at`.
 *
 * Noon UTC on the picked day, deliberately: the backend stores a naive
 * datetime and every consumer reads its *date part* (`date(card.sold_at)` in
 * the CSV export, `.year` for the tax filter, `isoformat()` for the Sheets
 * mirror), so anchoring mid-day keeps the picked calendar date intact no
 * matter which zone submitted it. Midnight — either UTC's or the user's — sits
 * against a boundary that some reader on either side crosses.
 *
 * Returns null for a blank or malformed value so a caller can fall back to the
 * server's own stamp rather than sending `Invalid Date`.
 */
export function soldAtFromDateInput(dateStr) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr || '').trim())
  if (!match) return null
  const [, year, month, day] = match
  const stamp = Date.UTC(Number(year), Number(month) - 1, Number(day), 12, 0, 0)
  const asDate = new Date(stamp)
  if (Number.isNaN(stamp)) return null
  // Reject dates the calendar rolled over (2026-02-31 → March 3): the picker
  // cannot produce one, but a hand-typed value in a text-input fallback can.
  if (asDate.getUTCMonth() !== Number(month) - 1 || asDate.getUTCDate() !== Number(day)) return null
  return asDate.toISOString()
}
