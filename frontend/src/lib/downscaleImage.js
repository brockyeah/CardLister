// Client-side downscale of card photos before upload. Modern phone cameras
// produce 10-20MP JPEGs (3-6 MB); the server resizes to ≤2000px for the vision
// call anyway, so shipping more pixels than that only costs mobile upload time
// and Railway volume space. 2000px matches the largest server-side preset
// ("accuracy"), so no scan mode loses input quality.

export const MAX_DIMENSION_PX = 2000
export const JPEG_QUALITY = 0.85

// Only raster types we can safely re-encode; PDFs and unknown types pass through.
const DOWNSCALABLE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])

// Pure sizing math (unit-tested): null means "already small enough, don't touch".
export function targetDimensions(width, height, maxPx = MAX_DIMENSION_PX) {
  if (!width || !height) return null
  const longest = Math.max(width, height)
  if (longest <= maxPx) return null
  const scale = maxPx / longest
  return { width: Math.round(width * scale), height: Math.round(height * scale) }
}

export async function downscaleImage(file, maxPx = MAX_DIMENSION_PX) {
  if (!file || !DOWNSCALABLE_TYPES.has(file.type)) return file
  try {
    // from-image bakes EXIF rotation into the pixels — re-encoding to JPEG
    // drops the EXIF block, so relying on it would leave phone photos sideways.
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    try {
      const target = targetDimensions(bitmap.width, bitmap.height, maxPx)
      if (!target) return file
      const canvas = document.createElement('canvas')
      canvas.width = target.width
      canvas.height = target.height
      const ctx = canvas.getContext('2d')
      // JPEG has no alpha; flatten transparent PNGs onto white, not black.
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, target.width, target.height)
      ctx.drawImage(bitmap, 0, 0, target.width, target.height)
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
      if (!blob || blob.size >= file.size) return file
      const name = (file.name || 'card').replace(/\.[^.]+$/, '') + '.jpg'
      return new File([blob], name, { type: 'image/jpeg' })
    } finally {
      bitmap.close()
    }
  } catch {
    // Any decode/canvas failure falls back to the original — never block a scan.
    return file
  }
}
