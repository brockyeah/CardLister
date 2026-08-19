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
  // per word, each flag is indivisible even when it contains a space.
  const words = (v) => String(v || '').split(/\s+/).filter(Boolean)
  const units = [
    ...words(card.year ? String(card.year) : ''),
    ...words(card.brand),
    ...words(card.set_name),
    ...words(card.player_name),
    ...words(card.card_number ? `#${card.card_number}` : ''),
    ...flags.map((f) => words(f).join(' ')),
    ...words(card.team),
  ]
  const full = units.join(' ')
  return {
    title: truncateTitle(units),
    full,
    truncated: full.length > EBAY_TITLE_MAX,
    length: full.length,
  }
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
    if (candidate.length > EBAY_TITLE_MAX) {
      // A first unit over the cap has no boundary to fall back to.
      return kept || unit.slice(0, EBAY_TITLE_MAX).replace(/\s+$/, '')
    }
    kept = candidate
  }
  return kept
}
