import { describe, it, expect } from 'vitest'
import { targetDimensions, downscaleImage, MAX_DIMENSION_PX } from './downscaleImage'

describe('targetDimensions', () => {
  it('returns null when the longest side is already within the cap', () => {
    expect(targetDimensions(1600, 1200)).toBeNull()
    expect(targetDimensions(2000, 900)).toBeNull()
  })

  it('scales the longest side down to the cap, preserving aspect ratio', () => {
    // 4032×3024 is a typical 12MP phone photo.
    expect(targetDimensions(4032, 3024)).toEqual({ width: 2000, height: 1500 })
    // Portrait orientation scales by height.
    expect(targetDimensions(3024, 4032)).toEqual({ width: 1500, height: 2000 })
  })

  it('rounds to whole pixels', () => {
    const t = targetDimensions(3001, 2000)
    expect(t.width).toBe(2000)
    expect(t.height).toBe(Math.round(2000 * (2000 / 3001)))
  })

  it('respects a custom cap and handles degenerate sizes', () => {
    expect(targetDimensions(1000, 500, 100)).toEqual({ width: 100, height: 50 })
    expect(targetDimensions(0, 500)).toBeNull()
    expect(targetDimensions(undefined, undefined)).toBeNull()
  })

  it('default cap matches the largest server-side vision preset', () => {
    // backend/services/claude_vision.py "accuracy" preset resizes to 2000px —
    // the client must never send less than the server is willing to use.
    expect(MAX_DIMENSION_PX).toBe(2000)
  })
})

describe('downscaleImage passthrough', () => {
  it('returns PDFs untouched', async () => {
    const pdf = new File(['%PDF-1.4'], 'scan.pdf', { type: 'application/pdf' })
    expect(await downscaleImage(pdf)).toBe(pdf)
  })

  it('returns unknown/absent types and null untouched', async () => {
    const weird = new File(['x'], 'card.tiff', { type: 'image/tiff' })
    expect(await downscaleImage(weird)).toBe(weird)
    expect(await downscaleImage(null)).toBeNull()
  })
})
