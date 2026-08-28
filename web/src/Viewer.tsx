import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { timecode } from './timecode'
import type { Project } from './types'
import './Viewer.css'

/** How long the scrubber must be still before we ask for a real frame.
 *  Short enough to feel immediate, long enough not to spawn ffmpeg per pixel. */
const SETTLE_MS = 220

export function Viewer({ id, onBack }: { id: string; onBack: () => void }) {
  const [project, setProject] = useState<Project | null>(null)
  const [t, setT] = useState(0)
  const [proof, setProof] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    api.getProject(id).then(setProject).catch((e) => setFailed(e.message))
  }, [id])

  const source = project?.doc.source
  const fps = source?.fps ?? 30
  const dur = source?.duration ?? 0
  const step = 1 / (fps || 30)

  /* Asking for a real frame is the second half of the hybrid preview: the
     video element gives an instant approximation while scrubbing, and this
     replaces it with what the renderer actually produces. */
  const verify = useCallback((at: number) => {
    if (!project) return
    setFailed(null)
    const url = api.frameUrl(project.id, Math.max(0, at - project.doc.trim.start))
    const img = new Image()
    img.onload = () => setProof(url)
    img.onerror = () => setFailed('The renderer could not produce this frame.')
    img.src = url
  }, [project])

  const seek = useCallback((next: number) => {
    const clamped = Math.min(Math.max(0, next), dur)
    setT(clamped)
    setProof(null)                       // back to the approximation
    if (video.current) video.current.currentTime = clamped
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => verify(clamped), SETTLE_MS)
  }, [dur, verify])

  useEffect(() => {
    if (project) verify(0)
    return () => window.clearTimeout(timer.current)
  }, [project, verify])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement && e.target.type === 'text') return
      if (e.key === 'ArrowLeft') { e.preventDefault(); seek(t - (e.shiftKey ? step * 10 : step)) }
      if (e.key === 'ArrowRight') { e.preventDefault(); seek(t + (e.shiftKey ? step * 10 : step)) }
      if (e.key === 'Home') { e.preventDefault(); seek(0) }
      if (e.key === 'End') { e.preventDefault(); seek(dur) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [seek, t, step, dur])

  if (failed && !project) return <p className="error" style={{ margin: 32 }}>{failed}</p>
  if (!project || !source) return null

  const out = project.doc.output
  const verified = proof !== null

  return (
    <div className="viewer">
      <header className="bar">
        <button className="back" onClick={onBack}>← Library</button>
        <h2>{project.name}</h2>
        <div className="spec">
          <span>{source.width}×{source.height}</span>
          <span><span className="arrow">→</span> {out.width}×{out.height}</span>
          <span>{fps.toFixed(fps % 1 ? 2 : 0)} fps</span>
          <span>{project.has_audio ? 'audio' : 'silent'}</span>
        </div>
      </header>

      <div className="stage">
        <div className={`gate ${verified ? 'verified' : 'approx'}`}>
          <video
            ref={video}
            src={api.sourceUrl(project.id)}
            preload="auto"
            onLoadedMetadata={(e) => { e.currentTarget.currentTime = t }}
          />
          {proof && <img src={proof} alt={`Rendered frame at ${timecode(t, fps)}`} />}
        </div>
      </div>

      {failed && <p className="failed" style={{ padding: '0 20px' }}>{failed}</p>}

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
          <span className="tc-big">{timecode(t, fps)}</span>
          <span className="of">/ {timecode(dur, fps)}</span>
          <span className="frame-no">frame {Math.round(t * fps).toLocaleString()}</span>
          <span className="grow" />
          <span className="hint">
            <kbd className="arrow">←</kbd> <kbd className="arrow">→</kbd> step a frame
            &nbsp;·&nbsp; <kbd>Shift</kbd> for ten
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
