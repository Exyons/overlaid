// Mirrors drawtext_filter() in core/compile.py.
//
// The canvas backing store is sized to the output resolution, so every number
// here is in the same coordinate space ffmpeg works in and the two can be
// compared directly. Anywhere this file and compile.py disagree, the preview
// lies about where text will land -- so they are deliberately written to look
// like each other.

import type { Anchor, EditDoc, TextOverlay } from './types'

export interface Layout {
  /** Text block, excluding the plate. */
  x: number; y: number; w: number; h: number
  /** Plate, including its border width. */
  boxX: number; boxY: number; boxW: number; boxH: number
  sizePx: number
  lineHeight: number
  lines: string[]
  pad: number
}

export function measure(
  o: TextOverlay,
  doc: EditDoc,
  ctx: CanvasRenderingContext2D,
  fontFamily: string,
): Layout {
  const out = doc.output
  const sizePx = Math.max(1, Math.round(out.height * o.size))
  const lineSpacing = Math.round(sizePx * o.line_gap)
  const lines = o.text.split('\n')

  ctx.font = `${sizePx}px "${fontFamily}"`
  const w = Math.max(...lines.map((l) => ctx.measureText(l).width), 0)
  const lineHeight = sizePx + lineSpacing
  const h = lines.length * sizePx + (lines.length - 1) * lineSpacing

  const [x, y] = anchorPoint(o.anchor, o.x * out.width, o.y * out.height, w, h)
  const pad = o.box ? Math.max(2, Math.round(sizePx * o.box.pad)) : 0

  return {
    x, y, w, h, sizePx, lineHeight, lines, pad,
    boxX: x - pad, boxY: y - pad, boxW: w + pad * 2, boxH: h + pad * 2,
  }
}

/** The drawtext x/y expressions, resolved. See anchor_expr() in compile.py. */
export function anchorPoint(
  anchor: Anchor, ax: number, ay: number, tw: number, th: number,
): [number, number] {
  const [v, h] = anchor.split('-')
  const x = h === 'left' ? ax : h === 'center' ? ax - tw / 2 : ax - tw
  const y = v === 'top' ? ay : v === 'middle' ? ay - th / 2 : ay - th
  return [x, y]
}

/** Inverse of anchorPoint: where the anchor must sit to put the block here. */
export function anchorFrom(
  anchor: Anchor, x: number, y: number, tw: number, th: number,
): [number, number] {
  const [v, h] = anchor.split('-')
  const ax = h === 'left' ? x : h === 'center' ? x + tw / 2 : x + tw
  const ay = v === 'top' ? y : v === 'middle' ? y + th / 2 : y + th
  return [ax, ay]
}

export function hit(l: Layout, px: number, py: number): boolean {
  return px >= l.boxX && px <= l.boxX + l.boxW
      && py >= l.boxY && py <= l.boxY + l.boxH
}

export function draw(
  ctx: CanvasRenderingContext2D,
  o: TextOverlay,
  l: Layout,
  fontFamily: string,
): void {
  if (o.box) {
    ctx.fillStyle = withAlpha(o.box.color, o.box.alpha)
    ctx.fillRect(l.boxX, l.boxY, l.boxW, l.boxH)
  }
  ctx.font = `${l.sizePx}px "${fontFamily}"`
  ctx.fillStyle = o.color
  ctx.textBaseline = 'top'
  l.lines.forEach((line, i) => ctx.fillText(line, l.x, l.y + i * l.lineHeight))
}

function withAlpha(hex: string, alpha: number): string {
  const n = parseInt(hex.replace('#', ''), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Standard gap from the frame edge, as a share of height. Matches the CLI. */
export const MARGIN = 0.025

/** Where an overlay must sit to land in one of the nine frame positions.
 *
 * The nine-cell control names a place in the frame, not merely an alignment:
 * picking "top left" should put the text in the top-left corner. Anchoring it
 * to the matching corner is what makes that stable, because the text then grows
 * inward and a longer line cannot push itself off the edge.
 *
 * The plate's border grows outward from the text, so the margin absorbs it or
 * the rectangle bleeds off the frame.
 */
export function positionFor(
  anchor: Anchor, size: number, boxPad: number | null,
  outWidth: number, outHeight: number,
): { x: number; y: number } {
  const padH = boxPad === null ? 0 : size * boxPad
  const padW = padH * (outHeight / outWidth)
  const [v, h] = anchor.split('-')
  return {
    x: h === 'left' ? MARGIN + padW : h === 'right' ? 1 - MARGIN - padW : 0.5,
    y: v === 'top' ? MARGIN + padH : v === 'bottom' ? 1 - MARGIN - padH : 0.5,
  }
}

/** True when the overlay is sitting exactly where `positionFor` would put it,
 *  so the control can show "custom" after a drag rather than claiming a corner
 *  the text is no longer in. */
export function isAtPosition(
  o: TextOverlay, outWidth: number, outHeight: number,
): boolean {
  const p = positionFor(o.anchor, o.size, o.box ? o.box.pad : null, outWidth, outHeight)
  return Math.abs(p.x - o.x) < 0.002 && Math.abs(p.y - o.y) < 0.002
}
