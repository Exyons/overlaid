import { useCallback, useEffect, useRef } from 'react'
import { anchorFrom, draw, hit, measure } from './layout'
import type { EditDoc, TextOverlay } from './types'

/** The canvas is sized to the output resolution and scaled down by CSS, so all
 *  drawing and hit-testing happens in the same coordinate space ffmpeg uses.
 *  Nothing here converts between screen pixels and video pixels except the two
 *  functions that read pointer events. */
export function Canvas({
  doc, families, selected, showText, onSelect, onMove, onCommit, dragging, onDragChange,
}: {
  doc: EditDoc
  families: Record<string, string>
  selected: string | null
  /** False once a real rendered frame is on screen: that frame already contains
   *  the text, so drawing it again here would paint every overlay twice. */
  showText: boolean
  onSelect: (id: string | null) => void
  onMove: (id: string, x: number, y: number) => void
  onCommit: () => void
  dragging: boolean
  onDragChange: (dragging: boolean) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const grab = useRef<{ id: string; dx: number; dy: number } | null>(null)

  const toVideo = useCallback((e: { clientX: number; clientY: number }) => {
    const el = canvas.current!
    const r = el.getBoundingClientRect()
    return {
      x: ((e.clientX - r.left) / r.width) * doc.output.width,
      y: ((e.clientY - r.top) / r.height) * doc.output.height,
    }
  }, [doc.output.width, doc.output.height])

  /* Repaint on any document change. The overlay list is small and the canvas is
     only redrawn on edits, so there is no frame loop to manage. */
  useEffect(() => {
    const el = canvas.current
    const ctx = el?.getContext('2d')
    if (!el || !ctx) return

    ctx.clearRect(0, 0, el.width, el.height)
    for (const o of doc.overlays) {
      const family = families[o.font] ?? 'sans-serif'
      const l = measure(o, doc, ctx, family)
      if (showText) draw(ctx, o, l, family)

      if (o.id === selected) {
        // Scale the marquee with the canvas so it stays one screen pixel wide
        // whatever the output resolution.
        const unit = doc.output.width / (el.clientWidth || doc.output.width)
        ctx.strokeStyle = '#57d2d2'
        ctx.lineWidth = Math.max(1, unit)
        ctx.setLineDash([6 * unit, 4 * unit])
        ctx.strokeRect(l.boxX, l.boxY, l.boxW, l.boxH)
        ctx.setLineDash([])
      }
    }
  }, [doc, families, selected, showText])

  function pick(px: number, py: number): TextOverlay | null {
    const ctx = canvas.current?.getContext('2d')
    if (!ctx) return null
    // Topmost first: later overlays are drawn above earlier ones.
    for (let i = doc.overlays.length - 1; i >= 0; i--) {
      const o = doc.overlays[i]
      if (hit(measure(o, doc, ctx, families[o.font] ?? 'sans-serif'), px, py)) return o
    }
    return null
  }

  function onPointerDown(e: React.PointerEvent<HTMLCanvasElement>) {
    const { x, y } = toVideo(e)
    const found = pick(x, y)
    onSelect(found?.id ?? null)
    if (!found) return

    const ctx = canvas.current!.getContext('2d')!
    const l = measure(found, doc, ctx, families[found.font] ?? 'sans-serif')
    grab.current = { id: found.id, dx: x - l.x, dy: y - l.y }
    onDragChange(true)
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!grab.current) return
    const { x, y } = toVideo(e)
    const o = doc.overlays.find((v) => v.id === grab.current!.id)
    if (!o) return

    const ctx = canvas.current!.getContext('2d')!
    const l = measure(o, doc, ctx, families[o.font] ?? 'sans-serif')
    // The pointer moves the block; the stored value is the anchor point, so
    // convert back through the same anchor the renderer will apply.
    const [ax, ay] = anchorFrom(
      o.anchor, x - grab.current.dx, y - grab.current.dy, l.w, l.h)
    onMove(o.id,
      clamp(ax / doc.output.width),
      clamp(ay / doc.output.height))
  }

  function endDrag(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!grab.current) return
    grab.current = null
    onDragChange(false)
    onCommit()
    e.currentTarget.releasePointerCapture(e.pointerId)
  }

  return (
    <canvas
      ref={canvas}
      className={`overlay-canvas${dragging ? ' dragging' : ''}`}
      width={doc.output.width}
      height={doc.output.height}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    />
  )
}

const clamp = (v: number) => Math.min(1, Math.max(0, v))
