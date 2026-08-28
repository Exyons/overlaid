import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { EditDoc, TextOverlay } from './types'

/** How long editing must pause before the document is written to the server. */
const AUTOSAVE_MS = 700

/** Edits made within this window collapse into one undo step, so dragging a
 *  slider does not bury the previous state under two hundred entries. */
const COALESCE_MS = 500

const LIMIT = 100

export interface Edit {
  doc: EditDoc | null
  selected: string | null
  saving: boolean
  error: string | null
  canUndo: boolean
  canRedo: boolean
  select: (id: string | null) => void
  /** `tag` groups consecutive edits into one undo step (e.g. 'drag', 'size'). */
  update: (next: EditDoc, tag?: string) => void
  addOverlay: (o: TextOverlay) => void
  patchOverlay: (id: string, patch: Partial<TextOverlay>, tag?: string) => void
  removeOverlay: (id: string) => void
  undo: () => void
  redo: () => void
}

export function useEdit(projectId: string): Edit {
  const [doc, setDoc] = useState<EditDoc | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const past = useRef<EditDoc[]>([])
  const future = useRef<EditDoc[]>([])
  const lastTag = useRef<{ tag: string; at: number } | null>(null)
  const saveTimer = useRef<number | undefined>(undefined)
  const [, bump] = useState(0)

  useEffect(() => {
    api.getProject(projectId)
      .then((p) => { setDoc(p.doc); past.current = []; future.current = [] })
      .catch((e) => setError(e.message))
  }, [projectId])

  const save = useCallback((next: EditDoc) => {
    window.clearTimeout(saveTimer.current)
    saveTimer.current = window.setTimeout(() => {
      setSaving(true)
      api.saveDoc(projectId, next)
        .then(() => setError(null))
        .catch((e) => setError(e.message))
        .finally(() => setSaving(false))
    }, AUTOSAVE_MS)
  }, [projectId])

  const update = useCallback((next: EditDoc, tag?: string) => {
    setDoc((prev) => {
      if (prev) {
        const now = Date.now()
        const same = tag && lastTag.current?.tag === tag
          && now - lastTag.current.at < COALESCE_MS
        if (!same) {
          past.current = [...past.current, prev].slice(-LIMIT)
          future.current = []
        }
        lastTag.current = tag ? { tag, at: now } : null
      }
      return next
    })
    save(next)
    bump((n) => n + 1)
  }, [save])

  const patchOverlay = useCallback((id: string, patch: Partial<TextOverlay>, tag?: string) => {
    setDoc((prev) => {
      if (!prev) return prev
      const now = Date.now()
      const key = tag ? `${id}:${tag}` : undefined
      const same = key && lastTag.current?.tag === key
        && now - lastTag.current.at < COALESCE_MS
      if (!same) {
        past.current = [...past.current, prev].slice(-LIMIT)
        future.current = []
      }
      lastTag.current = key ? { tag: key, at: now } : null

      const next: EditDoc = {
        ...prev,
        overlays: prev.overlays.map((o) => (o.id === id ? { ...o, ...patch } : o)),
      }
      save(next)
      return next
    })
    bump((n) => n + 1)
  }, [save])

  const addOverlay = useCallback((o: TextOverlay) => {
    setDoc((prev) => {
      if (!prev) return prev
      past.current = [...past.current, prev].slice(-LIMIT)
      future.current = []
      lastTag.current = null
      const next = { ...prev, overlays: [...prev.overlays, o] }
      save(next)
      return next
    })
    setSelected(o.id)
    bump((n) => n + 1)
  }, [save])

  const removeOverlay = useCallback((id: string) => {
    setDoc((prev) => {
      if (!prev) return prev
      past.current = [...past.current, prev].slice(-LIMIT)
      future.current = []
      lastTag.current = null
      const next = { ...prev, overlays: prev.overlays.filter((o) => o.id !== id) }
      save(next)
      return next
    })
    setSelected((s) => (s === id ? null : s))
    bump((n) => n + 1)
  }, [save])

  const undo = useCallback(() => {
    setDoc((prev) => {
      const previous = past.current.at(-1)
      if (!prev || previous === undefined) return prev
      past.current = past.current.slice(0, -1)
      future.current = [prev, ...future.current].slice(0, LIMIT)
      lastTag.current = null
      save(previous)
      return previous
    })
    bump((n) => n + 1)
  }, [save])

  const redo = useCallback(() => {
    setDoc((prev) => {
      const next = future.current[0]
      if (!prev || next === undefined) return prev
      future.current = future.current.slice(1)
      past.current = [...past.current, prev].slice(-LIMIT)
      lastTag.current = null
      save(next)
      return next
    })
    bump((n) => n + 1)
  }, [save])

  return {
    doc, selected, saving, error,
    canUndo: past.current.length > 0,
    canRedo: future.current.length > 0,
    select: setSelected,
    update, addOverlay, patchOverlay, removeOverlay, undo, redo,
  }
}

let counter = 0
export function newOverlay(fontPath: string, text = 'Your Name'): TextOverlay {
  return {
    id: `o${Date.now().toString(36)}${counter++}`,
    type: 'text',
    text,
    x: 0.5, y: 0.5,
    anchor: 'middle-center',
    size: 0.05,
    font: fontPath,
    color: '#ffffff',
    box: { color: '#000000', alpha: 0.55, pad: 0.5 },
    line_gap: 0.35,
    start: null, end: null,
  }
}
