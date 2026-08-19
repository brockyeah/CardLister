import { describe, it, expect } from 'vitest'
import {
  MIN_COMPS_FOR_SPREAD,
  WIDE_SPREAD_RATIO,
  formatCompPrice,
  formatCompRange,
  spreadWarning,
  summarizeComps,
} from './compStats'

const comps = (...prices) => prices.map((price, i) => ({ title: `comp ${i}`, price }))

describe('summarizeComps', () => {
  it('returns null when there is nothing usable to summarize', () => {
    expect(summarizeComps([])).toBeNull()
    expect(summarizeComps(undefined)).toBeNull()
    expect(summarizeComps(null)).toBeNull()
  })

  it('reports the low and high of the comp set regardless of input order', () => {
    const s = summarizeComps(comps(12.5, 4, 90, 8))
    expect(s.count).toBe(4)
    expect(s.low).toBe(4)
    expect(s.high).toBe(90)
  })

  it('drops comps whose price will not parse, and counts what is left', () => {
    // A source that emits an unparseable price must not become $NaN in the
    // range, and the caption has to describe what it actually measured.
    const s = summarizeComps([
      { title: 'ok', price: 10 },
      { title: 'null price', price: null },
      { title: 'text', price: 'n/a' },
      { title: 'zero', price: 0 },
      { title: 'negative', price: -5 },
      { title: 'ok', price: 20 },
    ])
    expect(s.count).toBe(2)
    expect(s.low).toBe(10)
    expect(s.high).toBe(20)
  })

  it('reads numeric-string prices', () => {
    const s = summarizeComps([{ price: '15.00' }, { price: '5.00' }])
    expect(s.low).toBe(5)
    expect(s.high).toBe(15)
  })

  it('flags a set whose high is at least the wide-spread ratio above its low', () => {
    expect(summarizeComps(comps(10, 20, 30)).wide).toBe(true)
    expect(summarizeComps(comps(4, 8, 90)).wide).toBe(true)
  })

  it('leaves a tightly clustered set unflagged', () => {
    expect(summarizeComps(comps(8, 8.5, 9, 9.25)).wide).toBe(false)
  })

  it('does not flag a set too small to describe a distribution', () => {
    // Two comps at $5 and $20 are noise, not evidence of contamination.
    expect(MIN_COMPS_FOR_SPREAD).toBe(3)
    expect(summarizeComps(comps(5, 20)).wide).toBe(false)
    expect(summarizeComps(comps(5, 20, 20)).wide).toBe(true)
  })

  it('treats the ratio as inclusive at the boundary', () => {
    const boundary = 10 * WIDE_SPREAD_RATIO
    expect(summarizeComps(comps(10, 15, boundary)).wide).toBe(true)
    expect(summarizeComps(comps(10, 15, boundary - 0.01)).wide).toBe(false)
  })
})

describe('formatCompRange', () => {
  it('renders a low–high range as money', () => {
    expect(formatCompRange(summarizeComps(comps(4, 8, 90)))).toBe('$4.00 – $90.00')
  })

  it('collapses to one price when every comp agrees', () => {
    expect(formatCompRange(summarizeComps(comps(9.99, 9.99)))).toBe('$9.99')
  })

  it('renders nothing for an empty summary', () => {
    expect(formatCompRange(null)).toBe('')
  })
})

describe('formatCompPrice', () => {
  it('renders a usable price as money', () => {
    expect(formatCompPrice(12.5)).toBe('$12.50')
    expect(formatCompPrice('9.99')).toBe('$9.99')
  })

  it('marks a price the summary would have excluded as unavailable', () => {
    // A bare Number(null).toFixed(2) renders "$0.00" — a confident-looking
    // price that is simply wrong — while the range above the list excludes it.
    for (const bad of [null, undefined, '', 'n/a', NaN, 0, -5]) {
      expect(formatCompPrice(bad)).toBe('—')
    }
  })

  it('agrees with summarizeComps about which prices count', () => {
    const list = [{ price: 10 }, { price: null }, { price: 'n/a' }, { price: 20 }]
    const rendered = list.map((c) => formatCompPrice(c.price))
    expect(rendered.filter((r) => r !== '—')).toHaveLength(summarizeComps(list).count)
  })
})

describe('spreadWarning', () => {
  it('says nothing about a tight comp set', () => {
    expect(spreadWarning(summarizeComps(comps(8, 8.5, 9)))).toBeNull()
    expect(spreadWarning(null)).toBeNull()
  })

  it('names the multiple and points at the titles', () => {
    const warning = spreadWarning(summarizeComps(comps(10, 20, 100)))
    expect(warning).toContain('10×')
    expect(warning).toContain('median')
    expect(warning).toContain('Check the titles')
  })
})
