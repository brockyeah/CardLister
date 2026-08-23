import { describe, it, expect } from 'vitest'
import { countByStatus, queueLossSummary, retryQueueItem, scanResultPatch } from './scanQueue'

const item = (key, status, extra = {}) => ({ key, status, result: null, error: null, ...extra })

describe('countByStatus', () => {
  it('counts only the requested statuses', () => {
    const queue = [item('a', 'ready'), item('b', 'saved'), item('c', 'ready')]
    expect(countByStatus(queue, ['ready'])).toBe(2)
    expect(countByStatus(queue, ['saved'])).toBe(1)
    expect(countByStatus(queue, ['queued'])).toBe(0)
  })

  it('tolerates an empty or missing queue', () => {
    expect(countByStatus([], ['ready'])).toBe(0)
    expect(countByStatus(undefined, ['ready'])).toBe(0)
    expect(countByStatus(null, ['ready'])).toBe(0)
  })
})

describe('queueLossSummary', () => {
  it('returns null when there is nothing to lose', () => {
    expect(queueLossSummary([])).toBeNull()
    expect(queueLossSummary(undefined)).toBeNull()
    expect(queueLossSummary([item('a', 'saved'), item('b', 'saved')])).toBeNull()
  })

  it('treats an errored item as nothing to lose — it cost no tokens', () => {
    expect(queueLossSummary([item('a', 'error', { error: 'Scan failed' })])).toBeNull()
  })

  it('counts ready and scanning items as paid work', () => {
    const summary = queueLossSummary([
      item('a', 'ready'),
      item('b', 'scanning'),
      item('c', 'saved'),
    ])
    expect(summary.paid).toBe(2)
    expect(summary.pending).toBe(0)
    expect(summary.message).toContain('2 cards have already been scanned but not saved')
    expect(summary.message).toContain('cannot be recovered')
  })

  it('reports queued items separately from paid ones', () => {
    const summary = queueLossSummary([item('a', 'ready'), item('b', 'queued'), item('c', 'queued')])
    expect(summary.paid).toBe(1)
    expect(summary.pending).toBe(2)
    expect(summary.message).toContain('1 card has already been scanned')
    expect(summary.message).toContain('2 cards are still waiting to scan')
  })

  it('warns about pending work even when nothing has been scanned yet', () => {
    const summary = queueLossSummary([item('a', 'queued')])
    expect(summary.paid).toBe(0)
    expect(summary.pending).toBe(1)
    expect(summary.message).toContain('1 card is still waiting to scan')
    expect(summary.message).not.toContain('paid for')
  })
})

describe('retryQueueItem', () => {
  it('sends a failed item back to queued and clears its message', () => {
    const queue = [item('a', 'error', { error: 'Scan failed' }), item('b', 'ready')]
    const next = retryQueueItem(queue, 'a')
    expect(next[0].status).toBe('queued')
    expect(next[0].error).toBeNull()
    expect(next[1]).toBe(queue[1])
  })

  it('refuses to re-queue an item that is not errored', () => {
    // Re-queueing a `ready` item would pay for the same extraction twice.
    const queue = [item('a', 'ready'), item('b', 'scanning'), item('c', 'saved')]
    expect(retryQueueItem(queue, 'a')).toBe(queue)
    expect(retryQueueItem(queue, 'b')).toBe(queue)
    expect(retryQueueItem(queue, 'c')).toBe(queue)
  })

  it('returns the queue untouched for an unknown key', () => {
    const queue = [item('a', 'error')]
    expect(retryQueueItem(queue, 'nope')).toBe(queue)
  })

  it('preserves the file reference so the retry rescans the same photo', () => {
    const file = { name: 'front.jpg' }
    const queue = [item('a', 'error', { file, error: 'boom' })]
    expect(retryQueueItem(queue, 'a')[0].file).toBe(file)
  })
})

describe('scanResultPatch', () => {
  it('marks a failed extraction as error, not ready', () => {
    // scan.py returns a blank card as 200 with an `error` field when the
    // Anthropic call fails, so it resolves like a success. Marking it `ready`
    // hid the Retry button behind the one status that never renders it.
    const patch = scanResultPatch({ error: 'Anthropic call failed', player_name: '' })
    expect(patch.status).toBe('error')
    expect(patch.error).toBe('Anthropic call failed')
  })

  it('marks a clean result ready and keeps the payload', () => {
    const result = { player_name: 'Elly De La Cruz', error: '', image_path: '/uploads/abc.png' }
    expect(scanResultPatch(result)).toEqual({ status: 'ready', result })
  })

  it.each([
    { message: 'upstream gateway said hello' },
    { detail: 'Not Found' },
    'a raw HTML error page',
  ])('treats a truthy body that is not a scan response (%p) as an error', (body) => {
    // `/api/scan` always includes image_path — the upload is stored before
    // extraction, in mock mode and on failure alike. A 200 without it is a
    // proxy or gateway body, and `ready` would offer Review over nothing.
    const patch = scanResultPatch(body)
    expect(patch.status).toBe('error')
    expect(patch.error).toBeTruthy()
  })

  it.each([undefined, null, '', 0])('treats an empty response (%p) as an error', (empty) => {
    // Not just null-safety: `ready` is the only status that renders Review and
    // hides Retry, and reviewQueueItem bails on `!result` — so `ready` here
    // means an inert button and no way back. Retry is the honest affordance.
    const patch = scanResultPatch(empty)
    expect(patch.status).toBe('error')
    expect(patch.error).toBeTruthy()
  })

  it('a no-data scan is not counted as paid work', () => {
    const queue = [{ key: 'a', status: scanResultPatch(null).status }]
    expect(queueLossSummary(queue)).toBeNull()
  })

  it('an errored item is not counted as paid work', () => {
    // scan.py records a UsageEvent only `if usage:`, and usage is None on the
    // failed-extraction path — so the clear-queue warning must not claim it.
    const queue = [{ key: 'a', status: scanResultPatch({ error: 'boom' }).status }]
    expect(queueLossSummary(queue)).toBeNull()
  })
})
