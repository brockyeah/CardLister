// Reclaimable-photo reporting for the Analytics manage-data panel.
//
// `/api/scan` writes the upload to the Railway volume *before* extraction and
// only records a `Scan` row when the extraction both succeeded and was real,
// so every failed or mock scan leaves a file referenced by nothing. The
// cleanup tool that sweeps them has existed since 2026-07-30, but the only way
// to find out whether there was anything to sweep was to press the button that
// offers to delete — so it ran when someone thought to look, which on a volume
// that fills silently is not a plan.
//
// Pure so it can be unit-tested: the frontend suite runs in a node environment
// with no jsdom, so component behaviour is only testable through the functions
// it delegates to.

// A sweep is "bulk" at or above this share of the uploads directory...
const BULK_SHARE = 0.5
// ...but only once there are enough files for the share to mean anything. Two
// orphans out of three files is 67% and entirely ordinary; ten is a pattern.
const BULK_MIN_COUNT = 10

/**
 * Whether this orphan set looks like lost photo *links* rather than genuinely
 * abandoned scans.
 *
 * The case this exists for: inventory restored from CSV. The export carries no
 * photo columns, so every restored card comes back with a null `image_path`
 * and every photo on the volume is suddenly an orphan — the cleanup tool would
 * cheerfully delete the entire photo library, and each deletion is final.
 * Genuine orphans accumulate a few at a time from failed and mock scans, so
 * they never reach this share.
 */
export function isBulkOrphanSweep(orphans) {
  const count = orphans?.count ?? 0
  const total = orphans?.total_files ?? 0
  return total > 0 && count >= BULK_MIN_COUNT && count / total >= BULK_SHARE
}

/**
 * The count to show on the storage tile, or null when the figure is unknown.
 *
 * Null and zero are deliberately different: zero means the sweep was run and
 * found nothing, null means the lookup failed and we do not know. Rendering a
 * failed lookup as "0 reclaimable" would be the same fail-open the tile exists
 * to close — it would say the volume is tidy on exactly the request that could
 * not check.
 */
export function orphanCount(orphans) {
  const count = orphans?.count
  return typeof count === 'number' && Number.isFinite(count) && count >= 0 ? count : null
}

/**
 * One line of context under the tile: how much space a cleanup would free, or
 * the warning that this set is probably lost links rather than junk.
 *
 * The warning belongs *here*, beside the number, and not only in the
 * confirmation dialog: the dialog is read by someone who has already decided
 * to clean up, which is the worst moment to learn that cleaning up is the
 * wrong thing to do.
 */
export function orphanHint(orphans, formatBytes) {
  const count = orphanCount(orphans)
  if (count == null) return 'Could not check'
  if (count === 0) return 'Nothing to reclaim'
  if (isBulkOrphanSweep(orphans)) {
    return `${formatBytes(orphans.bytes)} — but that is most of the photos on the server; check before deleting`
  }
  return `${formatBytes(orphans.bytes)} reclaimable`
}
