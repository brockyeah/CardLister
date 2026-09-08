import { describe, it, expect } from 'vitest'
import { formatArticleAge } from './articleAge.js'

describe('formatArticleAge', () => {
  it('calls the current day today', () => {
    expect(formatArticleAge(0)).toBe('today')
  })

  it('counts whole days back', () => {
    expect(formatArticleAge(1)).toBe('1d ago')
    expect(formatArticleAge(12)).toBe('12d ago')
  })

  it('reads a future-stamped feed entry as today, not "-1d ago"', () => {
    // The server subtracts the entry's timestamp from its own UTC clock, so a
    // feed running slightly ahead produces a negative age.
    expect(formatArticleAge(-1)).toBe('today')
  })

  it('says nothing when the feed carried no publish date', () => {
    // The byline is rendered only when this is non-empty, so an undated
    // article shows no byline at all rather than a bare separator — which is
    // what makes dropping the duplicated source line safe.
    expect(formatArticleAge(null)).toBe('')
    expect(formatArticleAge(undefined)).toBe('')
    expect(formatArticleAge('3')).toBe('')
    expect(formatArticleAge(NaN)).toBe('')
  })
})
