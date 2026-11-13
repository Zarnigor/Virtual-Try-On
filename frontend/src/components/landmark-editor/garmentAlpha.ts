import type { AlphaInfo } from './neckHole'

/**
 * Alpha of the loaded garment PNG: visible bounding box (alpha > 0) and solid area (alpha > 128, the neck_hole area
 * rule). { bbox: null, area: null } when the canvas cannot read the pixels (cross-origin): the server still checks.
 */
export function garmentAlpha(img: HTMLImageElement): AlphaInfo {
  try {
    const c = document.createElement('canvas')
    c.width = img.naturalWidth
    c.height = img.naturalHeight
    const ctx = c.getContext('2d')
    if (!ctx) return { bbox: null, area: null }
    ctx.drawImage(img, 0, 0)
    const { data } = ctx.getImageData(0, 0, c.width, c.height)
    let x0 = c.width, y0 = c.height, x1 = -1, y1 = -1, area = 0
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        const a = data[(y * c.width + x) * 4 + 3]
        if (a > 128) area++
        if (a > 0) {
          if (x < x0) x0 = x
          if (x > x1) x1 = x
          if (y < y0) y0 = y
          if (y > y1) y1 = y
        }
      }
    }
    return { bbox: x1 < 0 ? null : { x0, y0, x1, y1 }, area }
  } catch {
    return { bbox: null, area: null } // tainted canvas
  }
}
