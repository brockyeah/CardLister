import { describe, expect, it } from 'vitest'
import { formatApiError, isCanceled } from './apiError.js'

const axiosErr = (detail) => ({ response: { data: { detail } }, message: 'Request failed with status code 422' })

describe('formatApiError', () => {
  it('passes plain string details through', () => {
    expect(formatApiError(axiosErr('Invalid username or password'))).toBe('Invalid username or password')
  })

  it('joins 422 validation arrays into a renderable string', () => {
    const err = axiosErr([
      { loc: ['body', 'quantity'], msg: 'Input should be a valid integer', type: 'int_type' },
      { loc: ['body', 'listed_price'], msg: 'Input should be greater than 0', type: 'greater_than' },
    ])
    expect(formatApiError(err)).toBe('Input should be a valid integer; Input should be greater than 0')
  })

  it('never returns a non-string for malformed detail shapes', () => {
    expect(formatApiError(axiosErr([{ no_msg: true }]), 'Save failed.')).toBe('Save failed.')
    expect(formatApiError(axiosErr({ nested: 'object' }), 'Save failed.')).toBe('Save failed.')
    expect(formatApiError(axiosErr(''), 'Save failed.')).toBe('Save failed.')
  })

  it('falls back when there is no response at all (network error)', () => {
    expect(formatApiError(new Error('Network Error'), 'Scan failed.')).toBe('Scan failed.')
    expect(formatApiError(undefined, 'Scan failed.')).toBe('Scan failed.')
  })

  it('says a timed-out request may still have been done by the server', () => {
    // The shape axios produces when `timeout` fires: no response, code
    // ECONNABORTED. The generic fallback ("Scan failed.") is wrong here in the
    // way that costs money — the server may have finished the scan and billed
    // it, and a blind retry pays for it twice.
    const err = Object.assign(new Error('timeout of 300000ms exceeded'), { code: 'ECONNABORTED' })
    const msg = formatApiError(err, 'Scan failed.')
    expect(msg).toMatch(/took too long/)
    expect(msg).toMatch(/may have finished it anyway/)
  })

  it('prefers the server detail over the timeout message when both exist', () => {
    // A 504 from a proxy carries a real response; the server said something,
    // so say that rather than guessing about billing.
    const err = Object.assign(axiosErr('Gateway timed out'), { code: 'ECONNABORTED' })
    expect(formatApiError(err, 'Scan failed.')).toBe('Gateway timed out')
  })
})

describe('isCanceled', () => {
  it('recognizes an axios cancel and a bare AbortError', () => {
    expect(isCanceled({ code: 'ERR_CANCELED' })).toBe(true)
    expect(isCanceled({ name: 'CanceledError' })).toBe(true)
    expect(isCanceled(Object.assign(new Error('aborted'), { name: 'AbortError' }))).toBe(true)
  })

  it('does not swallow real failures', () => {
    // A cancel is suppressed rather than shown, so a false positive here is a
    // scan failure the user never hears about.
    expect(isCanceled({ code: 'ECONNABORTED' })).toBe(false)
    expect(isCanceled(new Error('Network Error'))).toBe(false)
    expect(isCanceled(axiosErr('Boom'))).toBe(false)
    expect(isCanceled(undefined)).toBe(false)
  })
})
