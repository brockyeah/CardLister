import { describe, expect, it } from 'vitest'
import { flagImplausibleSalePrice, salePriceConfirmMessage } from './salePriceSanity.js'

describe('flagImplausibleSalePrice', () => {
  it('returns null when the two prices are the same order of magnitude', () => {
    expect(flagImplausibleSalePrice(25, 25)).toBeNull()
    expect(flagImplausibleSalePrice(30, 25)).toBeNull()
    expect(flagImplausibleSalePrice(50, 25)).toBeNull() // 2× is legitimate re-pricing
    expect(flagImplausibleSalePrice(125, 25)).toBeNull() // 5× is legitimate
  })

  it('flags a price that is ~20× the listed price as much_higher', () => {
    const warn = flagImplausibleSalePrice(500, 25) // 20×
    expect(warn).toEqual({ kind: 'much_higher', factor: 20 })
  })

  it('flags a price that is much greater than 20× the listed price', () => {
    // The paradigm case: $25 card typed as $2500.
    const warn = flagImplausibleSalePrice(2500, 25)
    expect(warn?.kind).toBe('much_higher')
    expect(warn?.factor).toBe(100)
  })

  it('flags a price that is ~1/20 the listed price as much_lower', () => {
    // Digit dropped: $250 card sold accidentally at $12.50 → warn.
    const warn = flagImplausibleSalePrice(12.5, 250)
    expect(warn?.kind).toBe('much_lower')
    expect(warn?.factor).toBe(20)
  })

  it('is silent when there is no listed price to compare against', () => {
    // A card sold without ever being priced has no baseline — warning
    // against a phantom would refuse every such sale.
    expect(flagImplausibleSalePrice(2500, null)).toBeNull()
    expect(flagImplausibleSalePrice(2500, undefined)).toBeNull()
    expect(flagImplausibleSalePrice(2500, 0)).toBeNull()
    expect(flagImplausibleSalePrice(2500, '')).toBeNull()
  })

  it('is silent when the entered price is not a positive number', () => {
    // The bad-input side: only a real positive price is worth comparing.
    expect(flagImplausibleSalePrice(null, 25)).toBeNull()
    expect(flagImplausibleSalePrice(undefined, 25)).toBeNull()
    expect(flagImplausibleSalePrice(0, 25)).toBeNull()
    expect(flagImplausibleSalePrice(-5, 25)).toBeNull()
    expect(flagImplausibleSalePrice(NaN, 25)).toBeNull()
    expect(flagImplausibleSalePrice(Infinity, 25)).toBeNull()
  })

  it('accepts numeric strings — the modal used to hand a bare input value in', () => {
    expect(flagImplausibleSalePrice('2500', '25')).toEqual({ kind: 'much_higher', factor: 100 })
    expect(flagImplausibleSalePrice('  ', 25)).toBeNull() // Number('  ') is 0
  })
})

describe('salePriceConfirmMessage', () => {
  it('renders the much_higher message with the listed baseline', () => {
    const warn = { kind: 'much_higher', factor: 100 }
    expect(salePriceConfirmMessage(warn, 25)).toBe(
      "That's ~100× the listed price of $25.00. Confirm this is the actual sale price?",
    )
  })

  it('renders the much_lower message as a fraction', () => {
    const warn = { kind: 'much_lower', factor: 20 }
    expect(salePriceConfirmMessage(warn, 250)).toBe(
      "That's ~1/20 the listed price of $250.00. Confirm this is the actual sale price?",
    )
  })

  it('returns empty string when there is nothing to confirm', () => {
    expect(salePriceConfirmMessage(null, 25)).toBe('')
    expect(salePriceConfirmMessage(undefined, 25)).toBe('')
  })
})
