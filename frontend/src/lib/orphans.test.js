import { describe, expect, it } from 'vitest'
import { isBulkOrphanSweep, orphanCount, orphanHint } from './orphans.js'

// Stand-in for Analytics.jsx's fmtBytes — the hint is about wording and
// branching, not about byte formatting, which has its own home.
const bytes = (n) => `${n} B`

describe('isBulkOrphanSweep', () => {
  it('flags a set that is most of the uploads directory', () => {
    // The CSV-restore case: the export carries no photo columns, so every
    // restored card loses its image_path and every photo becomes an orphan.
    expect(isBulkOrphanSweep({ count: 40, total_files: 40 })).toBe(true)
    expect(isBulkOrphanSweep({ count: 10, total_files: 20 })).toBe(true)
  })

  it('does not flag the ordinary trickle of failed and mock scans', () => {
    expect(isBulkOrphanSweep({ count: 3, total_files: 40 })).toBe(false)
    // Above the share but below the count floor: 2 of 3 is 67% and entirely
    // ordinary on a nearly empty volume.
    expect(isBulkOrphanSweep({ count: 2, total_files: 3 })).toBe(false)
  })

  it('does not flag an empty or unknown directory', () => {
    // total_files 0 would divide by zero; a missing lookup must not warn.
    expect(isBulkOrphanSweep({ count: 0, total_files: 0 })).toBe(false)
    expect(isBulkOrphanSweep(null)).toBe(false)
    expect(isBulkOrphanSweep(undefined)).toBe(false)
    expect(isBulkOrphanSweep({})).toBe(false)
  })
})

describe('orphanCount', () => {
  it('reports the count when the lookup succeeded', () => {
    expect(orphanCount({ count: 0 })).toBe(0)
    expect(orphanCount({ count: 12 })).toBe(12)
  })

  it('reports null — not zero — when the figure is unknown', () => {
    // Rendering a failed lookup as "0 reclaimable" says the volume is tidy on
    // exactly the request that could not check.
    expect(orphanCount(null)).toBeNull()
    expect(orphanCount({})).toBeNull()
    expect(orphanCount({ count: '12' })).toBeNull()
    expect(orphanCount({ count: NaN })).toBeNull()
    expect(orphanCount({ count: -1 })).toBeNull()
  })
})

describe('orphanHint', () => {
  it('says how much a cleanup would free', () => {
    expect(orphanHint({ count: 4, bytes: 900, total_files: 80 }, bytes)).toBe('900 B reclaimable')
  })

  it('warns instead of inviting a delete when the set is most of the directory', () => {
    const hint = orphanHint({ count: 40, bytes: 5000, total_files: 40 }, bytes)
    expect(hint).toMatch(/most of the photos/)
    expect(hint).toMatch(/check before deleting/)
    expect(hint).not.toMatch(/reclaimable/)
  })

  it('distinguishes "nothing to reclaim" from "could not check"', () => {
    expect(orphanHint({ count: 0, bytes: 0, total_files: 12 }, bytes)).toBe('Nothing to reclaim')
    expect(orphanHint(null, bytes)).toBe('Could not check')
  })
})
