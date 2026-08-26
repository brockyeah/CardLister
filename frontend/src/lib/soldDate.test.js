import { describe, it, expect } from 'vitest'
import { todayLocalDate, soldAtFromDateInput } from './soldDate.js'

describe('todayLocalDate', () => {
  // Self-check, not ceremony: under a UTC runner the local date and the UTC
  // date are the same string, so every test below would pass against the very
  // bug they exist to catch. vite.config.js pins TZ=America/New_York; this
  // fails loudly if that ever stops taking effect.
  it('runs in a zone where local and UTC dates can differ', () => {
    expect(new Date().getTimezoneOffset()).not.toBe(0)
  })

  it('reads the local calendar date, not the UTC one', () => {
    // 2026-08-20T01:00Z is 2026-08-19 21:00 in New York — the evening case
    // that made the picker pre-fill tomorrow. Built from a UTC instant on
    // purpose: the two dates genuinely disagree, so the old
    // `toISOString().slice(0, 10)` would answer 2026-08-20 here.
    const evening = new Date(Date.UTC(2026, 7, 20, 1, 0, 0))
    expect(evening.toISOString().slice(0, 10)).toBe('2026-08-20')
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

  it('takes a two-digit-looking year literally', () => {
    // `Date.UTC(1, 0, 1)` means 1901, not year 1 — the legacy two-digit-year
    // remapping. A picker will not often produce `0001-01-01`, but silently
    // answering with a different year than the one typed is the one thing this
    // helper exists to stop. (CodeRabbit, PR #53.)
    expect(soldAtFromDateInput('0001-01-01')).toBe('0001-01-01T12:00:00.000Z')
    expect(soldAtFromDateInput('0050-08-20')).toBe('0050-08-20T12:00:00.000Z')
    expect(soldAtFromDateInput('0099-12-31')).toBe('0099-12-31T12:00:00.000Z')
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
