// Parity guard for the client-side eBay title mirror. The case table lives
// with the backend fixtures (backend/tests/fixtures/ebay_title_cases.json) and
// its expected values come from build_title — if these assertions fail, the
// mirror has drifted from the backend, not the other way around.
import { describe, expect, it } from 'vitest'
import { buildEbayTitle, truncateTitle, EBAY_TITLE_MAX } from './ebayTitle.js'
import table from '../../../backend/tests/fixtures/ebay_title_cases.json'

describe('buildEbayTitle parity with backend build_title', () => {
  for (const { name, card, expected } of table.cases) {
    it(name, () => {
      const result = buildEbayTitle(card)
      expect(result.title).toBe(expected)
      expect(result.title.length).toBeLessThanOrEqual(EBAY_TITLE_MAX)
      expect(result.truncated).toBe(result.full.length > EBAY_TITLE_MAX)
    })
  }

  it('still reports truncation when the preview drops a whole word', () => {
    // `truncated` drives the form's over-length warning and is measured on the
    // FULL title, not the rendered one — dropping to a word boundary makes the
    // rendered title shorter than the cap, and the warning must not vanish
    // with it.
    const result = buildEbayTitle({
      year: 2023, brand: 'Bowman', set_name: 'Chrome Prospects',
      player_name: 'Jackson Chourio', card_number: 'BCP-100', team: 'Brewers',
      is_rookie: true, is_first_bowman: true, is_refractor: true, serial_number: '99',
    })
    expect(result.title.length).toBeLessThan(EBAY_TITLE_MAX)
    expect(result.truncated).toBe(true)
    expect(result.length).toBe(result.full.length)
  })
})

describe('truncateTitle', () => {
  it('leaves a title within the cap untouched', () => {
    expect(truncateTitle(['2024', 'Topps', 'Chrome', 'Player', '#1']))
      .toBe('2024 Topps Chrome Player #1')
    const exact = 'x'.repeat(EBAY_TITLE_MAX)
    expect(truncateTitle([exact])).toBe(exact)
  })

  it('never leaves a partial unit at the end', () => {
    const units = ['2024', 'Topps', 'Chrome', 'Update', 'Sapphire', 'Edition',
      'Some', 'Player', 'Name', '#BCP-100', '1ST BOWMAN', 'REFRACTOR', '/99', 'Brewers']
    for (let count = 1; count <= units.length; count += 1) {
      const prefix = units.slice(0, count)
      const out = truncateTitle(prefix)
      expect(out.length).toBeLessThanOrEqual(EBAY_TITLE_MAX)
      // Whatever survives is a whole-unit prefix of the input.
      const kept = out ? out.split(' ') : []
      const rejoined = []
      for (const unit of prefix) {
        const unitWords = unit.split(' ')
        const slice = kept.slice(rejoined.length, rejoined.length + unitWords.length)
        if (slice.join(' ') !== unitWords.join(' ')) break
        rejoined.push(...unitWords)
      }
      expect(rejoined).toEqual(kept)
    }
  })

  it('hard-slices a single unit that has no boundary to fall back to', () => {
    expect(truncateTitle(['X'.repeat(95)])).toBe('X'.repeat(EBAY_TITLE_MAX))
    const out = truncateTitle(['Y'.repeat(90), 'Brewers'])
    expect(out.length).toBe(EBAY_TITLE_MAX)
    expect(out).not.toContain('Brewers')
  })

  it('does not let a shorter later flag jump ahead of a dropped one', () => {
    expect(truncateTitle(['A'.repeat(70), '1ST BOWMAN', 'AUTO'])).toBe('A'.repeat(70))
  })
})
