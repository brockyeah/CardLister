import { describe, it, expect, vi } from 'vitest'
import {
  DEFAULT_FEE_FIXED,
  DEFAULT_FEE_RATE,
  FEE_DISCLAIMER,
  estimateFees,
  formatFeeBasis,
  formatNet,
  parseFeeOverride,
} from './fees'

// The suite passes the rate explicitly wherever the arithmetic matters, so it
// pins the math rather than whatever a build-time override happens to set.
const RATE = DEFAULT_FEE_RATE
const FIXED = DEFAULT_FEE_FIXED

describe('estimateFees', () => {
  it('takes the percentage and the flat charge off a sale', () => {
    // $10 * 13.25% = $1.325, + $0.30 = $1.625 -> $1.63 at cent resolution.
    expect(estimateFees(10, RATE, FIXED)).toEqual({ fee: 1.63, net: 8.37 })
  })

  it('scales to a card worth real money', () => {
    expect(estimateFees(1000, RATE, FIXED)).toEqual({ fee: 132.8, net: 867.2 })
  })

  it('returns null for a price there is nothing to estimate from', () => {
    // Same rule as formatCompPrice: an unusable price must not become $0.00,
    // which reads as a real figure sitting next to real ones.
    for (const bad of [null, undefined, '', 'abc', NaN, Infinity, 0, -5]) {
      expect(estimateFees(bad, RATE, FIXED)).toBeNull()
    }
  })

  it('reads a numeric string, because the sale price arrives from an input', () => {
    // MarkSoldModal holds its price as the raw input value.
    expect(estimateFees('10', RATE, FIXED)).toEqual({ fee: 1.63, net: 8.37 })
  })

  it('reports a negative net rather than hiding it at zero', () => {
    // Below ~$0.35 the flat fee is larger than the sale. That is exactly the
    // case worth showing, so it is not clamped.
    const estimate = estimateFees(0.1, RATE, FIXED)
    expect(estimate.fee).toBe(0.31)
    expect(estimate.net).toBe(-0.21)
  })

  it('rounds fee and net to whole cents', () => {
    const { fee, net } = estimateFees(7.77, RATE, FIXED)
    expect(fee).toBe(Number(fee.toFixed(2)))
    expect(net).toBe(Number(net.toFixed(2)))
    // Net plus fee still reconstructs the sale price.
    expect(Number((fee + net).toFixed(2))).toBe(7.77)
  })

  it('honours a rate passed in, so a changed fee schedule is one edit', () => {
    expect(estimateFees(100, 0.1, 0)).toEqual({ fee: 10, net: 90 })
  })
})

describe('formatNet', () => {
  it('formats an estimate as money', () => {
    expect(formatNet(10, RATE, FIXED)).toBe('$8.37')
  })

  it('shows the comps list marker when there is no price', () => {
    expect(formatNet(null, RATE, FIXED)).toBe('—')
    expect(formatNet(0, RATE, FIXED)).toBe('—')
  })

  it('puts the minus in front of the amount on a losing sale', () => {
    // `$-0.21` skims as a price; `-$0.21` reads as the loss it is.
    expect(formatNet(0.1, RATE, FIXED)).toBe('-$0.21')
  })
})

describe('formatFeeBasis', () => {
  it('states the rate that produced the number', () => {
    expect(formatFeeBasis(RATE, FIXED)).toBe('13.25% + $0.30')
  })

  it('does not leave float noise in the percentage', () => {
    // 0.07 * 100 is 7.000000000000001 in IEEE 754.
    expect(formatFeeBasis(0.07, 0.3)).toBe('7% + $0.30')
  })
})

describe('parseFeeOverride', () => {
  it('passes a valid override through', () => {
    expect(parseFeeOverride('0.1', 0.1325, { max: 1 })).toBe(0.1)
    expect(parseFeeOverride(0, 0.1325, { max: 1 })).toBe(0)
  })

  it('falls back when nothing is set', () => {
    expect(parseFeeOverride(undefined, 0.1325)).toBe(0.1325)
    expect(parseFeeOverride(null, 0.1325)).toBe(0.1325)
    expect(parseFeeOverride('', 0.1325)).toBe(0.1325)
  })

  it('rejects a percentage written where a fraction belongs', () => {
    // "13.25" would charge 1325% and quietly turn every net negative.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(parseFeeOverride('13.25', 0.1325, { max: 1 })).toBe(0.1325)
    expect(warn).toHaveBeenCalled()
    warn.mockRestore()
  })

  it('rejects unparseable and negative values, loudly', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    expect(parseFeeOverride('free', 0.3)).toBe(0.3)
    expect(parseFeeOverride('-1', 0.3)).toBe(0.3)
    expect(parseFeeOverride(NaN, 0.3)).toBe(0.3)
    expect(warn).toHaveBeenCalledTimes(3)
    warn.mockRestore()
  })
})

describe('FEE_DISCLAIMER', () => {
  it('says what the estimate leaves out', () => {
    // The figure is computed from the item price alone; eBay charges the fee
    // on shipping too. Wherever a net renders, this has to render with it.
    expect(FEE_DISCLAIMER).toMatch(/item price only/i)
    expect(FEE_DISCLAIMER).toMatch(/shipping/i)
  })
})
