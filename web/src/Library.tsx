import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { duration } from './timecode'
import type { Project } from './types'
import './Library.css'

const ACCEPT = '.mp4,.mov,.mkv,.webm,.avi,.m4v'

export function Library({ onOpen }: { onOpen: (id: string) => void }) {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  const refresh = useCallback(() => {
    api.listProjects().then(setProjects).catch((e) => setError(e.message))
  }, [])

  useEffect(refresh, [refresh])

  async function accept(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    setError(null)
    setProgress(0)
    try {
      const project = await api.upload(file, setProgress)
      onOpen(project.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setProgress(null)
    }
  }

  async function remove(p: Project) {
    setError(null)
    try {
      await api.remove(p.id)
      refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const hasProjects = !!projects?.length

  return (
    <div className="library">
      <header className="masthead">
        <h1>Overlaid</h1>
        <span className="rule" />
        <span className="count">
          {projects ? String(projects.length).padStart(2, '0') : '--'}
        </span>
      </header>
      <p className="tagline">
        Burn a name, roll number and department onto a video — then trim, crop
        and export it. Every preview is a real frame from the renderer.
      </p>

      {projects === null ? null : projects.length === 0 ? (
        <p className="empty">Nothing here yet. Drop a video above to start.</p>
      ) : (
        <ul className="slates">
          {projects.map((p) => (
            <li className="slate" key={p.id}>
              <div
                className="thumb"
                style={{ backgroundImage: `url(${api.frameUrl(p.id, p.doc.source.duration / 2)})` }}
              />
              <div>
                <button className="name" onClick={() => onOpen(p.id)}>{p.name}</button>
                <div className="meta">
                  <span>{p.doc.source.width}×{p.doc.source.height}</span>
                  <span>{duration(p.doc.source.duration)}</span>
                  <span>{p.doc.source.fps.toFixed(p.doc.source.fps % 1 ? 2 : 0)} fps</span>
                  <span>{p.has_audio ? 'audio' : 'silent'}</span>
                </div>
              </div>
              <div className="actions">
                <button onClick={() => onOpen(p.id)}>Open</button>
                <button className="del" onClick={() => remove(p)}>Delete</button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error">{error}</p>}

      <div
        className={`dropzone${over ? ' over' : ''}${hasProjects ? ' slim' : ''}`}
        onClick={() => input.current?.click()}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') input.current?.click() }}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); accept(e.dataTransfer.files) }}
        role="button"
        tabIndex={0}
      >
        {progress === null ? (
          <>
            <h2>Drop a video here</h2>
            <p>{hasProjects ? 'or click to browse' : 'MP4, MOV, MKV, WebM, AVI — up to 4 GB'}</p>
          </>
        ) : (
          <div className="uploading">
            <span className="label">Copying</span>
            <span className="meter"><i style={{ width: `${progress * 100}%` }} /></span>
            <span className="mono" style={{ fontSize: 13, color: 'var(--ink-dim)' }}>
              {Math.round(progress * 100)}%
            </span>
          </div>
        )}
        <input ref={input} type="file" accept={ACCEPT}
               onChange={(e) => accept(e.target.files)} />
      </div>

    </div>
  )
}
