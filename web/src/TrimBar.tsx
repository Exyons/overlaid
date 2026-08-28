import { useCallback, useRef } from 'react'
import { timecode } from './timecode'
import type { Trim } from './types'

/** Shortest clip a trim may leave, in seconds. */
const MIN_CLIP = 0.2

/**
 * The scrubber, with in and out handles.
 *
 * The bar always spans the whole source: trimming is non-destructive, so the
 * material outside the range still exists and should stay visible and
 * reachable. The excluded parts are dimmed rather than removed.
 */
export function TrimBar({
  t, duration, fps, trim, onSeek, onTrim, onCommit,
}: {
  t: number
  duration: number
  fps: number
  trim: Trim
  onSeek: (t: number) => void
  onTrim: (trim: Trim) => void
  onCommit: () => void
}) {
  const bar = useRef<HTMLDivElement>(null)
  const drag = useRef<'in' | 'out' | null>(null)

  const start = trim.start
  const end = trim.end ?? duration
  const pct = (v: number) => `${duration ? (v / duration) * 100 : 0}%`

  const timeAt = useCallback((clientX: number) => {
    const r = bar.current!.getBoundingClientRect()
    return Math.min(Math.max(0, ((clientX - r.left) / r.width) * duration), duration)
  }, [duration])

  function onPointerMove(e: React.PointerEvent) {
    if (!drag.current) return
    const at = timeAt(e.clientX)
    if (drag.current === 'in') {
      const next = Math.min(at, end - MIN_CLIP)
      onTrim({ ...trim, start: Math.max(0, next) })
      onSeek(Math.max(0, next))
    } else {
      const next = Math.max(at, start + MIN_CLIP)
      // Null means "to the end", which survives the source being replaced by a
      // longer file; only store a number when the out point is really moved in.
      onTrim({ ...trim, end: next >= duration - 1e-3 ? null : next })
      onSeek(Math.min(next, duration))
    }
  }

  function endDrag(e: React.PointerEvent) {
    if (!drag.current) return
    drag.current = null
    ;(e.target as Element).releasePointerCapture?.(e.pointerId)
    onCommit()
  }

  function grab(e: React.PointerEvent, which: 'in' | 'out') {
    e.stopPropagation()
    drag.current = which
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }

  const trimmed = start > 0 || trim.end !== null

  return (
    <div className="trim">
      <div
        ref={bar}
        className="scrub"
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <span className="excluded" style={{ left: 0, width: pct(start) }} />
        <span className="excluded" style={{ left: pct(end), right: 0 }} />
        <span className="kept" style={{ left: pct(start), width: pct(end - start) }} />
        <span className="played" style={{ width: pct(t) }} />

        <input
          type="range" min={0} max={duration || 0} step={1 / (fps || 30)} value={t}
          aria-label="Position"
          onChange={(e) => onSeek(Number(e.target.value))}
        />

        <span
          className="trim-handle in" style={{ left: pct(start) }}
          onPointerDown={(e) => grab(e, 'in')}
          role="slider" aria-label="Clip start" tabIndex={0}
          aria-valuenow={start} aria-valuemin={0} aria-valuemax={duration}
        />
        <span
          className="trim-handle out" style={{ left: pct(end) }}
          onPointerDown={(e) => grab(e, 'out')}
          role="slider" aria-label="Clip end" tabIndex={0}
          aria-valuenow={end} aria-valuemin={0} aria-valuemax={duration}
        />
      </div>

      {trimmed && (
        <div className="trim-readout mono">
          <span>in {timecode(start, fps)}</span>
          <span>out {timecode(end, fps)}</span>
          <span className="kept-len">{timecode(end - start, fps)} kept</span>
          <button onClick={() => { onTrim({ start: 0, end: null }); onCommit() }}>
            Clear
          </button>
        </div>
      )}
    </div>
  )
}
