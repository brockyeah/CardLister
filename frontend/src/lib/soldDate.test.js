import { describe, it, expect } from 'vitest'
import { todayLocalDate, soldAtFromDateInput } from './soldDate.js'

describe('todayLocalDate', () => {
  it('reads the local calendar date, not the UTC one', () => {
    // 2026-08-19 21:30 in a UTC-4 zone is already 2026-08-20 in UTC — the case
    // that made the picker pre-fill tomorrow after 8pm EDT.
    const evening = new Date(2026, 7, 19, 21, 30, 0)
    expect(todayLocalDate(evening)).toBe('2026-08-19')
  })

  it('zero-pads month and day', () => {
    expect(todayLocalDate(new Date(2026, 0, 5, 12, 0, 0))).toBe('2026-01-05')
  })

  it('handles the last moment of a year', () => {
    expect(todayLocalDate(new Date(2026, 11, 31, 23, 59, 59))).toBe('2026-12-31')
  })
})

describe('soldAtFromDateInput', () => {
  it('anchors the picked day at noon UTC so its date part survives', () => {
    expect(soldAtFromDateInput('2026-08-20')).toBe('2026-08-20T12:00:00.000Z')
  })

  it('keeps the calendar date the user picked', () => {
    // The old `new Date('2026-01-01').toISOString()` produced UTC midnight,
    // which renders as 2025-12-31 west of UTC — a sale in the wrong tax year.
    const iso = soldAtFromDateInput('2026-01-01')
    expect(iso.slice(0, 10)).toBe('2026-01-01')
    expect(new Date(iso).getUTCFullYear()).toBe(2026)
  })

  it('round-trips every day of a leap February', () => {
    expect(soldAtFromDateInput('2028-02-29')).toBe('2028-02-29T12:00:00.000Z')
  })

  it('returns null for blank, missing, or malformed values', () => {
    expect(soldAtFromDateInput('')).toBeNull()
    expect(soldAtFromDateInput(null)).toBeNull()
    expect(soldAtFromDateInput(undefined)).toBeNull()
    expect(soldAtFromDateInput('08/20/2026')).toBeNull()
    expect(soldAtFromDateInput('2026-8-20')).toBeNull()
  })

  it('rejects a date the calendar would roll over', () => {
    expect(soldAtFromDateInput('2026-02-31')).toBeNull()
    expect(soldAtFromDateInput('2026-13-01')).toBeNull()
  })
})
