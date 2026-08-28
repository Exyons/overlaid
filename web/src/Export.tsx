import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { fileSize } from './timecode'
import type { EncoderInfo, Preset, Render } from './types'

/** How often a running render is polled. Renders take seconds to minutes, so
 *  this is about keeping the bar honest, not about latency. */
const POLL_MS = 500

/** Mirrors QUALITY_WORDS in core/compile.py. Shown because a bare number gives
 *  no clue that 100 is "indistinguishable from the source" rather than
 *  "lossless", which is a far larger and far slower thing to ask for. */
function qualityWord(q: number): string {
  if (q >= 95) return 'Visually lossless'
  if (q >= 80) return 'Very high'
  if (q >= 60) return 'High'
  if (q >= 35) return 'Good'
  return 'Smaller file'
}

export function Export({ projectId, disabled }: { projectId: string; disabled: boolean }) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [encoders, setEncoders] = useState<EncoderInfo[]>([])
  const [preset, setPreset] = useState('mp4')
  const [quality, setQuality] = useState(75)
  const [accel, setAccel] = useState('auto')
  const [render, setRender] = useState<Render | null>(null)
  const [error, setError] = useState<string | null>(null)
  const poll = useRef<number | undefined>(undefined)

  useEffect(() => {
    api.presets().then(setPresets).catch(() => setPresets([]))
    api.encoders().then(setEncoders).catch(() => setEncoders([]))
    return () => window.clearInterval(poll.current)
  }, [])

  const chosen = presets.find((p) => p.name === preset)
  const running = render !== null && (render.status === 'queued' || render.status === 'running')
  const gpu = encoders.find((e) => e.kind === 'gpu')

  async function start() {
    setError(null)
    try {
      const started = await api.startRender(projectId, preset, quality, accel)
      setRender(started)
      window.clearInterval(poll.current)
      poll.current = window.setInterval(async () => {
        try {
          const next = await api.getRender(started.id)
          setRender(next)
          if (next.status === 'done' || next.status === 'failed') {
            window.clearInterval(poll.current)
          }
        } catch {
          window.clearInterval(poll.current)
        }
      }, POLL_MS)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <section className="export">
      <div className="field">
        <label className="label" htmlFor="ex-format">Format</label>
        <select
          id="ex-format" value={preset} disabled={running}
          onChange={(e) => setPreset(e.target.value)}
        >
          {presets.map((p) => (
            <option key={p.name} value={p.name}>{p.name.toUpperCase()}</option>
          ))}
        </select>
      </div>

      {chosen?.has_quality && (
        <div className="field">
          <label className="label" htmlFor="ex-quality">
            Quality <span className="value">{qualityWord(quality)}</span>
          </label>
          <input
            id="ex-quality" type="range" min={0} max={100} step={5}
            value={quality} disabled={running}
            onChange={(e) => setQuality(Number(e.target.value))}
          />
          <p className="note">
            {quality >= 95
              ? 'Indistinguishable from the source. Larger file, slower to write.'
              : 'The source is already compressed, so higher is not sharper past a point.'}
          </p>
        </div>
      )}

      {preset === 'mp4' && gpu && (
        <div className="field">
          <label className="label" htmlFor="ex-accel">Encoder</label>
          <select
            id="ex-accel" value={accel} disabled={running}
            onChange={(e) => setAccel(e.target.value)}
          >
            <option value="auto">{gpu.label} — faster</option>
            <option value="cpu">CPU — smaller file</option>
          </select>
          <p className="note">
            The graphics chip encodes several times faster; libx264 spends longer
            and gets more picture into the same bitrate.
          </p>
        </div>
      )}

      {chosen?.warn && <p className="warn">{chosen.warn}</p>}

      <button className="go" onClick={start} disabled={disabled || running}>
        {running ? 'Exporting' : 'Export'}
      </button>

      {render && (
        <div className="job">
          {running && (
            <>
              <span className="meter">
                <i style={{ width: `${render.progress * 100}%` }} />
              </span>
              <span className="pct mono">
                {Math.round(render.progress * 100)}%
                {render.encoder && <> &middot; {render.encoder}</>}
              </span>
            </>
          )}
          {render.status === 'done' && (
            <>
              <a className="download" href={api.renderFileUrl(render.id)} download>
                Save {render.preset.toUpperCase()}
              </a>
              <span className="pct mono">
                {render.size !== null && fileSize(render.size)}
                {render.encoder && <> &middot; {render.encoder}</>}
              </span>
            </>
          )}
          {render.status === 'failed' && (
            <p className="warn error-text">{render.error ?? 'The render failed.'}</p>
          )}
        </div>
      )}

      {error && <p className="warn error-text">{error}</p>}
    </section>
  )
}
