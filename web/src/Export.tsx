import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Preset, Render } from './types'

/** How often a running render is polled. Renders take seconds to minutes, so
 *  this is about keeping the bar honest, not about latency. */
const POLL_MS = 500

export function Export({ projectId, disabled }: { projectId: string; disabled: boolean }) {
  const [presets, setPresets] = useState<Preset[]>([])
  const [preset, setPreset] = useState('mp4')
  const [quality, setQuality] = useState(60)
  const [render, setRender] = useState<Render | null>(null)
  const [error, setError] = useState<string | null>(null)
  const poll = useRef<number | undefined>(undefined)

  useEffect(() => {
    api.presets().then(setPresets).catch(() => setPresets([]))
    return () => window.clearInterval(poll.current)
  }, [])

  const chosen = presets.find((p) => p.name === preset)
  const running = render !== null && (render.status === 'queued' || render.status === 'running')

  async function start() {
    setError(null)
    try {
      const started = await api.startRender(projectId, preset, quality)
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
            Quality <span className="value">{quality}</span>
          </label>
          <input
            id="ex-quality" type="range" min={0} max={100} step={5}
            value={quality} disabled={running}
            onChange={(e) => setQuality(Number(e.target.value))}
          />
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
              <span className="pct mono">{Math.round(render.progress * 100)}%</span>
            </>
          )}
          {render.status === 'done' && (
            <a className="download" href={api.renderFileUrl(render.id)} download>
              Save {render.preset.toUpperCase()}
            </a>
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
