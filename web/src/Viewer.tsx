import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { Canvas } from './Canvas'
import { CropBox } from './CropBox'
import { Export } from './Export'
import { FULL_FRAME, FramePanel, outputForCrop } from './FramePanel'
import { TrimBar } from './TrimBar'
import { PauseIcon, PlayIcon } from './Icons'
import { useLoadedFonts } from './fonts'
import { Inspector } from './Inspector'
import { newOverlay, useEdit } from './store'
import { timecode } from './timecode'
import type { Crop, EditDoc, Output, Project, Trim } from './types'
import './Viewer.css'

/** How long the scrubber must be still before a real frame is fetched. Short
 *  enough to feel immediate, long enough not to spawn ffmpeg per pixel. */
const SETTLE_MS = 220

const FALLBACK_FONT = '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'

/** Speed presets. Beyond these the audio needs several atempo stages and the
 *  result stops being useful for anything but a time-lapse. */
const SPEEDS = [0.5, 1, 1.5, 2, 4]

export function Viewer({ id, onBack }: { id: string; onBack: () => void }) {
  const [project, setProject] = useState<Project | null>(null)
  const [t, setT] = useState(0)
  const [proof, setProof] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [tab, setTab] = useState<'text' | 'frame' | 'export'>('text')
  const [aspect, setAspect] = useState<number | null>(null)
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

  /* Choosing a crop means looking at the part of the picture the crop would
     throw away, so while the crop tool is open the frame is rendered from a
     document with the crop lifted and the overlays dropped -- their positions
     are relative to the output, which is exactly what is being changed. */
  const cropModeRef = useRef(false)

  const verify = useCallback((at: number) => {
    const current = docRef.current
    if (!current) return
    setFailed(null)
    inflight.current?.abort()          // a newer request supersedes an older one
    const ctrl = new AbortController()
    inflight.current = ctrl
    const asked: EditDoc = cropModeRef.current
      ? { ...current, crop: FULL_FRAME, overlays: [],
          output: { ...current.output, width: current.source.width,
                    height: current.source.height, fit: 'letterbox' } }
      : current
    api.liveFrame(id, Math.max(0, at), asked, ctrl.signal)
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

  /* Speed is a property of the edit, so the preview has to play at it too --
     otherwise the only way to hear or see what 4x looks like is to export it.
     preservesPitch matches what atempo does to the audio on export, so the
     preview sounds like the file will. */
  useEffect(() => {
    const el = video.current
    if (!el || !doc) return
    el.playbackRate = doc.speed
    el.preservesPitch = true
  }, [doc?.speed, doc])

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

  const cropping = tab === 'frame'
  cropModeRef.current = cropping

  const setCrop = useCallback((crop: Crop, tag: string | undefined = 'crop') => {
    const d = docRef.current
    if (d) edit.update({ ...d, crop }, tag)
  }, [edit])

  const setTrim = useCallback((trim: Trim) => {
    const d = docRef.current
    if (d) edit.update({ ...d, trim }, 'trim')
  }, [edit])

  const setOutput = useCallback((output: Output) => {
    const d = docRef.current
    if (d) edit.update({ ...d, output })
  }, [edit])

  const setSpeed = useCallback((speed: number) => {
    const d = docRef.current
    if (d) edit.update({ ...d, speed })
  }, [edit])

  if (failed && !project) return <p className="error" style={{ margin: 32 }}>{failed}</p>
  if (!project || !doc || !source) return null

  const out = doc.output
  const clipLength = (doc.trim.end ?? dur) - doc.trim.start
  const verified = proof !== null && !dragging && !playing && !cropping
  const selected = doc.overlays.find((o) => o.id === edit.selected) ?? null

  /* The video element holds the whole source, so it is scaled up and offset
     until only the cropped region shows through its window. Without this the
     uncropped picture reappeared underneath every time the rendered frame was
     invalidated, which read as the crop being lost. The crop tool wants the
     whole source, so it opts out. */
  const c = doc.crop
  const videoWindow: React.CSSProperties = cropping
    ? { inset: 0, width: '100%', height: '100%' }
    : {
        width: `${100 / c.w}%`,
        height: `${100 / c.h}%`,
        left: `${(-c.x * 100) / c.w}%`,
        top: `${(-c.y * 100) / c.h}%`,
      }

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
          <div
            className={`gate ${verified ? 'verified' : 'approx'}`}
            style={{ '--ar': cropping
              ? `${source.width} / ${source.height}`
              : `${out.width} / ${out.height}` } as React.CSSProperties}
          >
            <div className="video-view">
              <video
                ref={video}
                src={api.sourceUrl(id)}
                preload="auto"
                style={videoWindow}
                onLoadedMetadata={(e) => {
                e.currentTarget.currentTime = t
                e.currentTarget.playbackRate = doc.speed
                e.currentTarget.preservesPitch = true
              }}
                onPlay={() => setPlaying(true)}
                onPause={() => { setPlaying(false); invalidate() }}
                onTimeUpdate={(e) => {
                  if (playing) setT(e.currentTarget.currentTime)
                }}
                onEnded={() => setPlaying(false)}
              />
            </div>
            {proof && !dragging && !playing && (
              <img src={proof} alt={`Rendered frame at ${timecode(t, fps)}`} />
            )}
            {cropping ? (
              <CropBox
                crop={doc.crop}
                source={source}
                aspect={aspect}
                onChange={setCrop}
                onCommit={() => {
                  // Cropping changes the shape of the picture, so the output
                  // follows it. Leaving the old size would letterbox the new
                  // crop back into the frame it was cut out of. The height is
                  // kept, so this is a reshape rather than a rescale.
                  const d = docRef.current
                  // No height argument: the crop's own size, never larger.
                  if (d) edit.update({ ...d, output: outputForCrop(d) })
                  invalidate()
                }}
              />
            ) : (
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
            )}
          </div>
        </div>

        <div className="panel">
          <div className="tabs" role="tablist">
            {(['text', 'frame', 'export'] as const).map((name) => (
              <button
                key={name}
                role="tab"
                aria-selected={tab === name}
                className={tab === name ? 'on' : ''}
                onClick={() => { setTab(name); invalidate() }}
              >
                {name === 'frame' ? 'Crop & size' : name === 'text' ? 'Text' : 'Export'}
              </button>
            ))}
          </div>

          {tab === 'text' && (
            <>
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
            </>
          )}

          {tab === 'frame' && (
            <FramePanel
              doc={doc}
              aspect={aspect}
              onAspect={setAspect}
              onCrop={(crop) => { setCrop(crop); invalidate() }}
              onOutput={(output) => { setOutput(output); invalidate() }}
              onReset={() => {
                edit.update({ ...doc, crop: FULL_FRAME })
                invalidate()
              }}
            />
          )}

          {tab === 'export' && <Export projectId={id} disabled={edit.saving} />}
        </div>
      </div>

      {(failed || edit.error) && <p className="failed">{failed ?? edit.error}</p>}

      <div className="transport">
        <TrimBar
          t={t}
          duration={dur}
          fps={fps}
          trim={doc.trim}
          onSeek={seek}
          onTrim={setTrim}
          onCommit={invalidate}
        />
        <div className="row">
          <div className="speed" role="group" aria-label="Speed">
            <span className="label">Speed</span>
            {SPEEDS.map((s) => (
              <button
                key={s}
                className={doc.speed === s ? 'on' : ''}
                aria-pressed={doc.speed === s}
                onClick={() => { setSpeed(s); invalidate() }}
              >
                {s}&times;
              </button>
            ))}
            {doc.speed !== 1 && (
              <span className="out-len mono">
                {timecode(clipLength / doc.speed, fps)} out
              </span>
            )}
          </div>
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
