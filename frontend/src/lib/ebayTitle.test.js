// Parity guard for the client-side eBay title mirror. The case table lives
// with the backend fixtures (backend/tests/fixtures/ebay_title_cases.json) and
// its expected values come from build_title — if these assertions fail, the
// mirror has drifted from the backend, not the other way around.
import { describe, expect, it } from 'vitest'
import { buildEbayTitle, EBAY_TITLE_MAX } from './ebayTitle.js'
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
})
