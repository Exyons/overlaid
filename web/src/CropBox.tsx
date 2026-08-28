import { useCallback, useRef } from 'react'
import type { Crop, Source } from './types'

/** Smallest crop, as a share of the source. Below this the handles overlap and
 *  the rectangle stops being draggable. */
const MIN = 0.05

type Handle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w' | 'move'

const HANDLES: Handle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']

const clamp01 = (v: number) => Math.min(1, Math.max(0, v))

/**
 * The crop rectangle, drawn over an uncropped frame.
 *
 * Crop is stored as a fraction of the *source*, so everything here works in
 * that space and the component never needs to know the display size. An aspect
 * lock is expressed in output pixels rather than in normalised units, since
 * "16:9" means the shape of the finished picture, and the source's own pixels
 * are what the fractions are measured against.
 */
export function CropBox({
  crop, source, aspect, onChange, onCommit,
}: {
  crop: Crop
  source: Source
  /** Locked output aspect (width / height), or null for free-form. */
  aspect: number | null
  onChange: (crop: Crop) => void
  onCommit: () => void
}) {
  const layer = useRef<HTMLDivElement>(null)
  const drag = useRef<{ handle: Handle; start: Crop; ox: number; oy: number } | null>(null)

  const toFraction = useCallback((e: { clientX: number; clientY: number }) => {
    const r = layer.current!.getBoundingClientRect()
    return {
      x: (e.clientX - r.left) / r.width,
      y: (e.clientY - r.top) / r.height,
    }
  }, [])

  /** Height that gives `w` the locked aspect, in source fractions. */
  const heightFor = useCallback((w: number) => {
    if (aspect === null) return null
    return (w * source.width) / (aspect * source.height)
  }, [aspect, source.width, source.height])

  const widthFor = useCallback((h: number) => {
    if (aspect === null) return null
    return (h * source.height * aspect) / source.width
  }, [aspect, source.width, source.height])

  function onPointerDown(e: React.PointerEvent, handle: Handle) {
    e.stopPropagation()
    const p = toFraction(e)
    drag.current = { handle, start: crop, ox: p.x, oy: p.y }
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: React.PointerEvent) {
    const d = drag.current
    if (!d) return
    const p = toFraction(e)
    const dx = p.x - d.ox
    const dy = p.y - d.oy
    onChange(resize(d.handle, d.start, dx, dy))
  }

  function endDrag(e: React.PointerEvent) {
    if (!drag.current) return
    drag.current = null
    ;(e.target as Element).releasePointerCapture?.(e.pointerId)
    onCommit()
  }

  function resize(handle: Handle, s: Crop, dx: number, dy: number): Crop {
    if (handle === 'move') {
      // Moving never changes the size, so it is clamped rather than trimmed.
      return {
        ...s,
        x: clamp01(Math.min(s.x + dx, 1 - s.w)),
        y: clamp01(Math.min(s.y + dy, 1 - s.h)),
      }
    }

    let { x, y, w, h } = s
    if (handle.includes('w')) { const nx = clamp01(Math.min(s.x + dx, s.x + s.w - MIN)); w = s.x + s.w - nx; x = nx }
    if (handle.includes('e')) { w = Math.max(MIN, Math.min(1 - s.x, s.w + dx)) }
    if (handle.includes('n')) { const ny = clamp01(Math.min(s.y + dy, s.y + s.h - MIN)); h = s.y + s.h - ny; y = ny }
    if (handle.includes('s')) { h = Math.max(MIN, Math.min(1 - s.y, s.h + dy)) }

    if (aspect !== null) {
      // Corner handles drive from whichever edge moved; side handles derive the
      // other dimension so the shape is preserved rather than fought over.
      const horizontal = handle === 'e' || handle === 'w'
      if (horizontal) {
        const nh = heightFor(w)!
        h = Math.min(nh, 1)
        w = widthFor(h)!
        // Grow around the vertical centre so a side handle does not walk the
        // rectangle up the frame.
        y = clamp01(Math.min(s.y + (s.h - h) / 2, 1 - h))
      } else if (handle === 'n' || handle === 's') {
        const nw = widthFor(h)!
        w = Math.min(nw, 1)
        h = heightFor(w)!
        x = clamp01(Math.min(s.x + (s.w - w) / 2, 1 - w))
        if (handle === 'n') y = clamp01(Math.min(s.y + s.h - h, 1 - h))
      } else {
        const nh = heightFor(w)!
        if (y + nh > 1 || nh > 1) {
          h = Math.min(1 - y, 1)
          w = widthFor(h)!
        } else {
          h = nh
        }
        if (handle.includes('n')) y = clamp01(Math.min(s.y + s.h - h, 1 - h))
        if (handle.includes('w')) x = clamp01(Math.min(s.x + s.w - w, 1 - w))
      }
    }

    // Nothing may leave the frame: the renderer rejects a crop that does.
    w = Math.min(w, 1 - x)
    h = Math.min(h, 1 - y)
    return { x, y, w: Math.max(MIN, w), h: Math.max(MIN, h) }
  }

  const pct = (v: number) => `${v * 100}%`

  return (
    <div
      ref={layer}
      className="crop-layer"
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      <div
        className="crop-rect"
        style={{ left: pct(crop.x), top: pct(crop.y), width: pct(crop.w), height: pct(crop.h) }}
        onPointerDown={(e) => onPointerDown(e, 'move')}
      >
        <div className="thirds" aria-hidden="true" />
        {HANDLES.map((h) => (
          <span
            key={h}
            className={`handle ${h}`}
            onPointerDown={(e) => onPointerDown(e, h)}
          />
        ))}
      </div>
    </div>
  )
}

/** Pixel size a crop produces, rounded to even for yuv420p. */
export function cropSize(crop: Crop, source: Source): [number, number] {
  const w = Math.max(2, Math.round(crop.w * source.width) & ~1)
  const h = Math.max(2, Math.round(crop.h * source.height) & ~1)
  return [w, h]
}
