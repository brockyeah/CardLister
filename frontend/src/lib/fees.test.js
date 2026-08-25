import { describe, it, expect, vi } from 'vitest'
import {
  DEFAULT_FEE_SCHEDULE,
  FEE_CAVEAT,
  estimateFees,
  feeDisclaimer,
  formatFeeSchedule,
  formatNet,
  parseFeeOverride,
} from './fees'

// The suite passes the schedule explicitly wherever the arithmetic matters, so
// it pins the math rather than whatever a build-time override happens to set.
const S = DEFAULT_FEE_SCHEDULE

describe('estimateFees', () => {
  it('takes the percentage and the per-order charge off a small sale', () => {
    // $10 * 13.25% = $1.325, + $0.30 (at or under the $10 threshold) = $1.625
    // -> $1.63 at cent resolution.
    expect(estimateFees(10, S)).toEqual({ fee: 1.63, net: 8.37 })
  })

  it('switches to the higher per-order fee just above $10', () => {
    // The threshold is "$0.30 on orders of $10 or less" — so $10.00 itself
    // pays $0.30 and a cent more pays $0.40. A flat $0.30 understated the fee
    // on every card over $10, which is most of the inventory.
    expect(estimateFees(10, S).fee).toBe(1.63)
    expect(estimateFees(10.01, S).fee).toBe(1.73)
  })

  it('applies the per-order step to an ordinary card', () => {
    // $24.99 * 13.25% = $3.311175, + $0.40 = $3.711175 -> $3.71.
    expect(estimateFees(24.99, S)).toEqual({ fee: 3.71, net: 21.28 })
  })

  it('scales to a card worth real money', () => {
    // $1000 * 13.25% = $132.50, + $0.40 = $132.90.
    expect(estimateFees(1000, S)).toEqual({ fee: 132.9, net: 867.1 })
  })

  it('charges the reduced rate only on the portion above the tier', () => {
    // $10,000: 13.25% of the first $7,500 = $993.75, plus 2.35% of the
    // remaining $2,500 = $58.75, plus $0.40 = $1,052.90. Applying 2.35% to
    // the whole sale would understate the fee by ~$820.
    expect(estimateFees(10000, S)).toEqual({ fee: 1052.9, net: 8947.1 })
  })

  it('treats the tier itself as fully within the higher rate', () => {
    // $7,500 * 13.25% = $993.75, + $0.40 = $994.15. One cent more crosses.
    expect(estimateFees(7500, S).fee).toBe(994.15)
    expect(estimateFees(7500.01, S).fee).toBe(994.15)
  })

  it('returns null for a price there is nothing to estimate from', () => {
    // Same rule as formatCompPrice: an unusable price must not become $0.00,
    // which reads as a real figure sitting next to real ones.
    for (const bad of [null, undefined, '', 'abc', NaN, Infinity, 0, -5]) {
      expect(estimateFees(bad, S)).toBeNull()
    }
  })

  it('reads a numeric string, because the sale price arrives from an input', () => {
    // MarkSoldModal holds its price as the raw input value.
    expect(estimateFees('10', S)).toEqual({ fee: 1.63, net: 8.37 })
  })

  it('reports a negative net rather than hiding it at zero', () => {
    // Below ~$0.35 the flat fee is larger than the sale. That is exactly the
    // case worth showing, so it is not clamped.
    const estimate = estimateFees(0.1, S)
    expect(estimate.fee).toBe(0.31)
    expect(estimate.net).toBe(-0.21)
  })

  it('rounds fee and net to whole cents', () => {
    const { fee, net } = estimateFees(7.77, S)
    expect(fee).toBe(Number(fee.toFixed(2)))
    expect(net).toBe(Number(net.toFixed(2)))
    // Net plus fee still reconstructs the sale price.
    expect(Number((fee + net).toFixed(2))).toBe(7.77)
  })

  it('honours a schedule passed in, so a changed fee table is one edit', () => {
    const flat = { rate: 0.1, rateAbove: 0.1, tier: Infinity, fixed: 0, fixedAbove: 0, fixedThreshold: 0 }
    expect(estimateFees(100, flat)).toEqual({ fee: 10, net: 90 })
  })
})

describe('formatNet', () => {
  it('formats an estimate as money', () => {
    expect(formatNet(10, S)).toBe('$8.37')
  })

  it('shows the comps list marker when there is no price', () => {
    expect(formatNet(null, S)).toBe('—')
    expect(formatNet(0, S)).toBe('—')
  })

  it('puts the minus in front of the amount on a losing sale', () => {
    // `$-0.21` skims as a price; `-$0.21` reads as the loss it is.
    expect(formatNet(0.1, S)).toBe('-$0.21')
  })
})

describe('formatFeeSchedule', () => {
  it('states every rate and threshold that produced the number', () => {
    expect(formatFeeSchedule(S)).toBe(
      '13.25% of the sale (2.35% above $7,500) plus $0.40 per order over $10, $0.30 at or under.',
    )
  })

  it('does not leave float noise in a percentage', () => {
    // 0.07 * 100 is 7.000000000000001 in IEEE 754.
    expect(formatFeeSchedule({ ...S, rate: 0.07 })).toMatch(/^7% of the sale/)
  })
})

describe('feeDisclaimer', () => {
  it('carries both the schedule and what the estimate leaves out', () => {
    // The figure is computed from the item price alone; eBay charges the fee
    // on shipping too. Wherever a net renders, this renders with it.
    const note = feeDisclaimer(S)
    expect(note).toContain(formatFeeSchedule(S))
    expect(note).toContain(FEE_CAVEAT)
    expect(FEE_CAVEAT).toMatch(/item price only/i)
    expect(FEE_CAVEAT).toMatch(/shipping/i)
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
