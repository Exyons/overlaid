import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { Canvas } from './Canvas'
import { Export } from './Export'
import { PauseIcon, PlayIcon } from './Icons'
import { useLoadedFonts } from './fonts'
import { Inspector } from './Inspector'
import { newOverlay, useEdit } from './store'
import { timecode } from './timecode'
import type { Project } from './types'
import './Viewer.css'

/** How long the scrubber must be still before a real frame is fetched. Short
 *  enough to feel immediate, long enough not to spawn ffmpeg per pixel. */
const SETTLE_MS = 220

const FALLBACK_FONT = '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'

export function Viewer({ id, onBack }: { id: string; onBack: () => void }) {
  const [project, setProject] = useState<Project | null>(null)
  const [t, setT] = useState(0)
  const [proof, setProof] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [playing, setPlaying] = useState(false)
  const video = useRef<HTMLVideoElement>(null)
  const timer = useRef<number | undefined>(undefined)

  const edit = useEdit(id)
  const doc = edit.doc
  const families = useLoadedFonts(doc?.overlays.map((o) => o.font) ?? [])

  useEffect(() => {
    api.getProject(id).then(setProject).catch((e) => setFailed(e.message))
  }, [id])

  const source = doc?.source
  const fps = source?.fps ?? 30
  const dur = source?.duration ?? 0
  const step = 1 / (fps || 30)

  /* The second half of the hybrid preview: the video element and canvas give an
     instant approximation, and this replaces it with what the renderer really
     produces. Both come from the same filter chain, so a confirmed frame is
     what the export will contain. */
  const inflight = useRef<AbortController | null>(null)

  /* The document is read through a ref rather than closed over. A callback
     capturing `doc` renders whichever version existed when it was created, so
     an edit followed by an immediate preview would ask for the state before the
     edit -- and the frame that came back would look like the change had been
     undone. */
  const docRef = useRef(doc)
  docRef.current = doc

  const verify = useCallback((at: number) => {
    const current = docRef.current
    if (!current) return
    setFailed(null)
    inflight.current?.abort()          // a newer request supersedes an older one
    const ctrl = new AbortController()
    inflight.current = ctrl
    api.liveFrame(id, Math.max(0, at - current.trim.start), current, ctrl.signal)
      .then((url) => {
        setProof((old) => { if (old) URL.revokeObjectURL(old); return url })
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setFailed(e.message)
      })
  }, [id])

  const tRef = useRef(t)
  tRef.current = t

  const invalidate = useCallback(() => {
    setProof(null)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => verify(tRef.current), SETTLE_MS)
  }, [verify])

  const seek = useCallback((next: number) => {
    const clamped = Math.min(Math.max(0, next), dur)
    setT(clamped)
    setProof(null)
    if (video.current) video.current.currentTime = clamped
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => verify(clamped), SETTLE_MS)
  }, [dur, verify])

  const togglePlay = useCallback(() => {
    const el = video.current
    if (!el) return
    if (el.paused) {
      setProof(null)          // playback shows the video, not a rendered frame
      window.clearTimeout(timer.current)
      void el.play()
    } else {
      el.pause()
    }
  }, [])

  useEffect(() => {
    if (doc) verify(0)
    return () => { window.clearTimeout(timer.current); inflight.current?.abort() }
    // Only on first load; later invalidations go through invalidate().
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!doc])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null
      const typing = target instanceof HTMLTextAreaElement
        || target instanceof HTMLInputElement
        || target instanceof HTMLSelectElement
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        e.shiftKey ? edit.redo() : edit.undo()
        invalidate()
        return
      }
      if (typing) return
      if (e.key === ' ') { e.preventDefault(); togglePlay(); return }
      if (e.key === 'ArrowLeft') { e.preventDefault(); seek(t - (e.shiftKey ? step * 10 : step)) }
      if (e.key === 'ArrowRight') { e.preventDefault(); seek(t + (e.shiftKey ? step * 10 : step)) }
      if (e.key === 'Home') { e.preventDefault(); seek(0) }
      if (e.key === 'End') { e.preventDefault(); seek(dur) }
      if ((e.key === 'Delete' || e.key === 'Backspace') && edit.selected) {
        e.preventDefault()
        edit.removeOverlay(edit.selected)
        invalidate()
      }
      if (e.key === 'Escape') edit.select(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [seek, t, step, dur, edit, invalidate, togglePlay])

  if (failed && !project) return <p className="error" style={{ margin: 32 }}>{failed}</p>
  if (!project || !doc || !source) return null

  const out = doc.output
  const verified = proof !== null && !dragging && !playing
  const selected = doc.overlays.find((o) => o.id === edit.selected) ?? null

  return (
    <div className="viewer">
      <header className="bar">
        <button className="back" onClick={onBack}>&larr; Library</button>
        <h2>{project.name}</h2>
        <div className="history">
          <button onClick={() => { edit.undo(); invalidate() }}
                  disabled={!edit.canUndo} title="Undo (Ctrl+Z)">Undo</button>
          <button onClick={() => { edit.redo(); invalidate() }}
                  disabled={!edit.canRedo} title="Redo (Ctrl+Shift+Z)">Redo</button>
        </div>
        <div className="spec">
          {edit.saving && <span className="saving">Saving</span>}
          <span>{source.width}&times;{source.height}</span>
          <span><span className="arrow">&rarr;</span> {out.width}&times;{out.height}</span>
          <span>{fps.toFixed(fps % 1 ? 2 : 0)} fps</span>
        </div>
      </header>

      <div className="workspace">
        <div className="stage">
          <div className={`gate ${verified ? 'verified' : 'approx'}`}>
            <video
              ref={video}
              src={api.sourceUrl(id)}
              preload="auto"
              onLoadedMetadata={(e) => { e.currentTarget.currentTime = t }}
              onPlay={() => setPlaying(true)}
              onPause={() => { setPlaying(false); invalidate() }}
              onTimeUpdate={(e) => {
                if (playing) setT(e.currentTarget.currentTime)
              }}
              onEnded={() => setPlaying(false)}
            />
            {proof && !dragging && !playing && (
              <img src={proof} alt={`Rendered frame at ${timecode(t, fps)}`} />
            )}
            <Canvas
              doc={doc}
              families={families}
              showText={!verified}
              onSelect={edit.select}
              onMove={(oid, x, y) => edit.patchOverlay(oid, { x, y }, 'drag')}
              onCommit={invalidate}
              dragging={dragging}
              onDragChange={setDragging}
            />
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <span className="label">Text</span>
            <button onClick={() => {
              edit.addOverlay(newOverlay(selected?.font ?? FALLBACK_FONT))
              invalidate()
            }}>Add text</button>
          </div>
          <Inspector
            overlay={selected}
            outputWidth={out.width}
            outputHeight={out.height}
            onPatch={(patch, tag) => {
              if (edit.selected) {
                edit.patchOverlay(edit.selected, patch, tag)
                invalidate()
              }
            }}
            onRemove={() => {
              if (edit.selected) { edit.removeOverlay(edit.selected); invalidate() }
            }}
          />
          <div className="panel-head">
            <span className="label">Export</span>
          </div>
          <Export projectId={id} disabled={edit.saving} />
        </div>
      </div>

      {(failed || edit.error) && <p className="failed">{failed ?? edit.error}</p>}

      <div className="transport">
        <div className="scrub">
          <span className="played" style={{ width: `${dur ? (t / dur) * 100 : 0}%` }} />
          <input
            type="range" min={0} max={dur || 0} step={step} value={t}
            aria-label="Position"
            onChange={(e) => seek(Number(e.target.value))}
          />
        </div>
        <div className="row">
          <button
            className="play"
            onClick={togglePlay}
            aria-label={playing ? 'Pause' : 'Play'}
            aria-pressed={playing}
            title={playing ? 'Pause (Space)' : 'Play (Space)'}
          >
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
          <span className="tc-big">{timecode(t, fps)}</span>
          <span className="of">/ {timecode(dur, fps)}</span>
          <span className="frame-no">frame {Math.round(t * fps).toLocaleString()}</span>
          <span className="grow" />
          <span className="hint">
            <kbd>Space</kbd> play &nbsp;&middot;&nbsp;
            <kbd className="arrow">&larr;</kbd> <kbd className="arrow">&rarr;</kbd> step a frame
          </span>
          <div className={`proof ${verified ? 'verified' : 'approx'}`}>
            <span className="lamp" />
            <span>{verified ? 'Rendered' : 'Approximate'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
