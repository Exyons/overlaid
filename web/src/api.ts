import type { EditDoc, Preset, Project } from './types'

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

  sourceUrl: (id: string) => `/api/projects/${id}/source`,
  frameUrl: (id: string, t: number) => `/api/projects/${id}/frame?t=${t.toFixed(3)}`,
}
