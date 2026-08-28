import type { EditDoc, EncoderInfo, Preset, Project, Render } from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  listProjects: () => fetch('/api/projects').then(json<Project[]>),

  getProject: (id: string) => fetch(`/api/projects/${id}`).then(json<Project>),

  upload(file: File, onProgress?: (fraction: number) => void) {
    // XHR rather than fetch: upload progress events have no fetch equivalent,
    // and a large video takes long enough that a progress bar earns its place.
    return new Promise<Project>((resolve, reject) => {
      const body = new FormData()
      body.append('file', file)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/projects')
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(e.loaded / e.total)
      }
      xhr.onload = () => {
        const parsed = (() => { try { return JSON.parse(xhr.responseText) } catch { return {} } })()
        if (xhr.status >= 200 && xhr.status < 300) resolve(parsed)
        else reject(new Error(parsed.detail ?? `Upload failed (${xhr.status})`))
      }
      xhr.onerror = () => reject(new Error('Upload failed: no response from the server'))
      xhr.send(body)
    })
  },

  saveDoc: (id: string, doc: EditDoc) =>
    fetch(`/api/projects/${id}/doc`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(doc),
    }).then(json<Project>),

  rename: (id: string, name: string) =>
    fetch(`/api/projects/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }).then(json<Project>),

  remove: async (id: string) => {
    const res = await fetch(`/api/projects/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(`Could not delete (${res.status})`)
  },

  presets: () => fetch('/api/presets').then(json<Preset[]>),

  encoders: () => fetch('/api/encoders').then(json<EncoderInfo[]>),

  startRender: (id: string, preset: string, quality: number, accel: string) =>
    fetch(`/api/projects/${id}/renders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ preset, quality, accel }),
    }).then(json<Render>),

  getRender: (id: string) => fetch(`/api/renders/${id}`).then(json<Render>),

  renderFileUrl: (id: string) => `/api/renders/${id}/file`,

  sourceUrl: (id: string) => `/api/projects/${id}/source`,

  /** A frame from the saved document. Used for library thumbnails. */
  frameUrl: (id: string, t: number) => `/api/projects/${id}/frame?t=${t.toFixed(3)}`,

  /** A frame from the document the editor is holding right now, saved or not.
   *  Returns an object URL the caller owns and must revoke. */
  async liveFrame(id: string, t: number, doc: EditDoc, signal?: AbortSignal) {
    const res = await fetch(`/api/projects/${id}/frame`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ t, doc }),
      signal,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `Preview failed (${res.status})`)
    }
    return URL.createObjectURL(await res.blob())
  },
}
