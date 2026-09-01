import { describe, it, expect } from 'vitest'
import { usableSuggestedPrice } from './pricing'

describe('usableSuggestedPrice', () => {
  it('returns the price from a real comp source', () => {
    expect(usableSuggestedPrice({ suggested_price: 24.99, source: 'ebay_sold' })).toBe(24.99)
    expect(usableSuggestedPrice({ suggested_price: 3.5, source: '130point' })).toBe(3.5)
    expect(usableSuggestedPrice({ suggested_price: 12, source: 'mavin' })).toBe(12)
  })

  it('refuses the $9.99 mock, which is what a fully failed lookup returns', () => {
    // The exact shape routers/pricing.py returns when every source fails —
    // and on Railway that is the common case, not the edge.
    expect(usableSuggestedPrice({
      comps: [],
      suggested_price: 9.99,
      source: 'mock',
      note: 'eBay: 403 | 130point: 403',
    })).toBeNull()
  })

  it('refuses a mock even if the mock price is ever changed', () => {
    // The guard is on the source, not on the magic number.
    expect(usableSuggestedPrice({ suggested_price: 45, source: 'mock' })).toBeNull()
  })

  it('treats a non-positive price as unset, like the listing-text endpoint', () => {
    expect(usableSuggestedPrice({ suggested_price: 0, source: 'ebay_sold' })).toBeNull()
    expect(usableSuggestedPrice({ suggested_price: -1, source: 'ebay_sold' })).toBeNull()
  })

  it('refuses a missing, null or non-numeric price', () => {
    expect(usableSuggestedPrice({ source: 'ebay_sold' })).toBeNull()
    expect(usableSuggestedPrice({ suggested_price: null, source: 'ebay_sold' })).toBeNull()
    // A string survives `> 0` and then throws on `.toFixed()` at the call site.
    expect(usableSuggestedPrice({ suggested_price: '24.99', source: 'ebay_sold' })).toBeNull()
    expect(usableSuggestedPrice({ suggested_price: NaN, source: 'ebay_sold' })).toBeNull()
    expect(usableSuggestedPrice({ suggested_price: Infinity, source: 'ebay_sold' })).toBeNull()
  })

  it('refuses a missing result rather than throwing', () => {
    // Inventory's catch handler substitutes its own object, but the Scanner
    // reads whatever the API returned.
    expect(usableSuggestedPrice(null)).toBeNull()
    expect(usableSuggestedPrice(undefined)).toBeNull()
  })

  it('accepts a price with no source rather than dropping it', () => {
    // Only 'mock' is disqualifying. An unlabelled response is a real lookup
    // whose source field went missing, and refusing it would silently discard
    // a good comp — the opposite of the bug this guard exists for.
    expect(usableSuggestedPrice({ suggested_price: 24.99 })).toBe(24.99)
  })
})
