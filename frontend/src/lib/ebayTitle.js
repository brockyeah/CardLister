// Client-side mirror of build_title() in backend/routers/ebay.py — the backend
// stays the source of truth for the copied listing text; this exists so the form
// can preview it live. Keep field order, flag order, and the 80-char cap in sync
// with the backend (see test_first_bowman.py for the canonical flag order).
export const EBAY_TITLE_MAX = 80

export function buildEbayTitle(card) {
  const flags = []
  if (card.is_rookie) flags.push('RC')
  if (card.is_first_bowman) flags.push('1ST BOWMAN')
  if (card.is_autograph) flags.push('AUTO')
  if (card.is_patch) flags.push('PATCH')
  if (card.is_refractor) flags.push('REFRACTOR')
  if (card.serial_number) {
    const sn = String(card.serial_number).trim()
    if (sn) flags.push(sn.startsWith('/') ? sn : `/${sn}`)
  }
  if (card.parallel_color) flags.push(String(card.parallel_color).toUpperCase())

  // Units the title may be cut between: free-text fields contribute one unit
  // per word, identifiers (each flag, and the card number) stay indivisible
  // even when they contain a space.
  const words = (v) => String(v || '').split(/\s+/).filter(Boolean)
  // Normalized like the serial above: whitespace-only contributes nothing
  // rather than a bare "#".
  const cardNoValue = words(card.card_number).join(' ')
  const cardNo = cardNoValue ? `#${cardNoValue}` : ''
  const units = [
    ...words(card.year ? String(card.year) : ''),
    ...words(card.brand),
    ...words(card.set_name),
    ...words(card.player_name),
    ...(cardNo ? [cardNo] : []),
    ...flags.map((f) => words(f).join(' ')).filter(Boolean),
    ...words(card.team),
  ]
  const full = units.join(' ')
  return {
    title: truncateTitle(units),
    full,
    truncated: titleLength(full) > EBAY_TITLE_MAX,
    length: titleLength(full),
  }
}

/**
 * Character count the way the backend measures it.
 *
 * Python's `len()` counts Unicode code points; JavaScript's `.length` counts
 * UTF-16 code units, so a single non-BMP character (an emoji in a player name
 * or note) counts as 1 in `build_title` and 2 here. Left alone, the preview
 * would report a card as over the limit — and truncate it — while the backend
 * copied the whole title to the clipboard, with the shared parity fixture
 * unable to catch it because the two sides disagree about what "80" means.
 * The backend is the source of truth (invariant #7), so the mirror adopts its
 * unit of measure.
 */
function titleLength(text) {
  return [...text].length
}

/**
 * Mirror of truncate_title() in backend/routers/ebay.py: join the units,
 * dropping whole ones that don't fit. Slicing at the 80th character turns a
 * `/99` serial into `/9`, `REFRACTOR` into `REFRACTO` and `1ST BOWMAN` into
 * `1ST` — titles that are not just shorter but wrong about the card. Dropping
 * the whole unit says less and nothing false.
 */
export function truncateTitle(units) {
  let kept = ''
  for (const unit of units) {
    const candidate = kept ? `${kept} ${unit}` : unit
    if (titleLength(candidate) > EBAY_TITLE_MAX) {
      // A first unit over the cap has no boundary to fall back to. Slice by
      // code point, not code unit, so the cut can't land inside a surrogate
      // pair and leave a lone surrogate in the title.
      return kept || [...unit].slice(0, EBAY_TITLE_MAX).join('').replace(/\s+$/, '')
    }
    kept = candidate
  }
  return kept
}
