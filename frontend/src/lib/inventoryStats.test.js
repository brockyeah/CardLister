import { describe, it, expect } from 'vitest'
import { cardQuantity, computeInventoryStats } from './inventoryStats'

describe('cardQuantity', () => {
  it('defaults to 1 when quantity is missing, null, or unusable', () => {
    expect(cardQuantity({})).toBe(1)
    expect(cardQuantity({ quantity: null })).toBe(1)
    expect(cardQuantity({ quantity: 0 })).toBe(1)
    expect(cardQuantity({ quantity: -4 })).toBe(1)
    expect(cardQuantity({ quantity: 'abc' })).toBe(1)
    expect(cardQuantity(undefined)).toBe(1)
  })

  it('reads numeric and numeric-string quantities', () => {
    expect(cardQuantity({ quantity: 3 })).toBe(3)
    expect(cardQuantity({ quantity: '5' })).toBe(5)
  })

  it('never floors a positive fraction down to zero copies', () => {
    // The API enforces an integer >= 1, but flooring 0.5 to 0 would silently
    // erase a real card rather than degrade to the documented default of 1.
    expect(cardQuantity({ quantity: 0.5 })).toBe(1)
    expect(cardQuantity({ quantity: 2.7 })).toBe(2)
  })
})

describe('computeInventoryStats', () => {
  const cards = [
    { status: 'active', quantity: 3, listed_price: 10 },
    { status: 'active', listed_price: 25 },
    { status: 'sold', quantity: 2, sold_price: 40 },
    { status: 'unlisted', quantity: 4, listed_price: 5 },
  ]

  it('counts copies, not rows', () => {
    const s = computeInventoryStats(cards)
    expect(s.total).toBe(10) // 3 + 1 + 2 + 4
    expect(s.listed).toBe(4) // 3 + 1
    expect(s.sold).toBe(2)
    expect(s.rowCount).toBe(4)
  })

  it('multiplies listed price by quantity for active value only', () => {
    const s = computeInventoryStats(cards)
    expect(s.activeValue).toBe(55) // 10*3 + 25*1; the unlisted qty-4 row is excluded
  })

  it('leaves revenue per-row — sold_price is what the sale brought in', () => {
    const s = computeInventoryStats(cards)
    expect(s.revenue).toBe(40) // not 40 * 2
  })

  it('counts revenue only from sold rows', () => {
    // The CSV importer fills sold_price from the "Sale Price" column whatever
    // the row's status, so an active row can carry one; counting it would
    // report revenue from a card still sitting in the box.
    const s = computeInventoryStats([
      ...cards,
      { status: 'active', listed_price: 12, sold_price: 999 },
    ])
    expect(s.revenue).toBe(40)
  })

  it('treats an empty or non-array input as zeroes', () => {
    for (const input of [[], null, undefined]) {
      expect(computeInventoryStats(input)).toEqual({
        total: 0, listed: 0, sold: 0, revenue: 0, activeValue: 0, rowCount: 0,
      })
    }
  })

  it('ignores null prices instead of producing NaN', () => {
    const s = computeInventoryStats([
      { status: 'active', quantity: 2, listed_price: null },
      { status: 'sold', sold_price: null },
    ])
    expect(s.activeValue).toBe(0)
    expect(s.revenue).toBe(0)
    expect(s.total).toBe(3)
  })
})
