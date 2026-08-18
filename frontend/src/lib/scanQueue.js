// Batch-scan queue helpers.
//
// The queue in Scanner.jsx moves each staged photo through
// `queued → scanning → ready → saved`, with `error` as a side exit. Two of
// those states represent money already spent: a `ready` item has been through
// a full Opus extraction and is waiting for the user to review it, and a
// `scanning` item is mid-call. Discarding either throws away the tokens as
// well as the review effort, and there is no way to get them back short of
// re-uploading the photo and paying for the scan again.
//
// These are pure so they can be unit-tested — the frontend suite runs in a
// node environment with no jsdom, so component behaviour is only testable
// through the functions it delegates to.

// Statuses whose work is unrecoverable if the queue is thrown away.
const PAID_STATUSES = ['ready', 'scanning']

/** How many queue items are currently in any of `statuses`. */
export function countByStatus(queue, statuses) {
  const wanted = new Set(statuses)
  return (queue || []).filter((q) => wanted.has(q?.status)).length
}

/**
 * What a "Clear queue" press would destroy, or null when it would destroy
 * nothing (an empty queue, or one where every item is already saved or
 * errored — an errored item cost nothing and holds no reviewed state).
 *
 * `paid` and `pending` are reported separately because they are not equally
 * bad: `pending` items have not been scanned yet, so re-staging those files
 * costs only the upload.
 */
export function queueLossSummary(queue) {
  const paid = countByStatus(queue, PAID_STATUSES)
  const pending = countByStatus(queue, ['queued'])
  if (paid === 0 && pending === 0) return null
  return { paid, pending, message: clearQueueMessage(paid, pending) }
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`
}

function clearQueueMessage(paid, pending) {
  const parts = []
  if (paid > 0) {
    parts.push(
      `${plural(paid, 'card has', 'cards have')} already been scanned but not saved — ` +
        `those scans are paid for and cannot be recovered.`,
    )
  }
  if (pending > 0) {
    parts.push(`${plural(pending, 'card is', 'cards are')} still waiting to scan.`)
  }
  return `Clear the batch queue? ${parts.join(' ')}`
}

/**
 * Send a failed item back to the front of the work list. The sequential
 * processor picks up whatever is `queued`, so flipping the status is the whole
 * retry — and clearing `error` matters so a second failure shows the new
 * message rather than the stale one.
 *
 * Only `error` items are retryable: re-queueing a `ready` item would silently
 * pay for the same extraction twice, and re-queueing `scanning` would run two
 * scans for one photo.
 */
export function retryQueueItem(queue, key) {
  let changed = false
  const next = (queue || []).map((q) => {
    if (q?.key !== key || q?.status !== 'error') return q
    changed = true
    return { ...q, status: 'queued', error: null }
  })
  return changed ? next : queue
}
