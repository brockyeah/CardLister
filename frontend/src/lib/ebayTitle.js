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

  const parts = [
    card.year ? String(card.year) : '',
    card.brand || '',
    card.set_name || '',
    card.player_name || '',
    card.card_number ? `#${card.card_number}` : '',
    flags.join(' '),
    card.team || '',
  ]
  const full = parts.filter(Boolean).join(' ').split(/\s+/).filter(Boolean).join(' ')
  const truncated = full.length > EBAY_TITLE_MAX
  const title = truncated ? full.slice(0, EBAY_TITLE_MAX).replace(/\s+$/, '') : full
  return { title, full, truncated, length: full.length }
}
