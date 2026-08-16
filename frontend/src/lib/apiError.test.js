import { describe, expect, it } from 'vitest'
import { formatApiError } from './apiError.js'

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
})
