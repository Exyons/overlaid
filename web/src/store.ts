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
  /** Replace the whole document -- crop, trim and output live outside overlays.
   *  `tag` groups consecutive edits into one undo step (e.g. 'drag', 'size'). */
  update: (next: EditDoc, tag?: string) => void
  patchOverlay: (id: string, patch: Partial<TextOverlay>, tag?: string) => void
  addOverlay: (o: TextOverlay) => void
  removeOverlay: (id: string) => void
  undo: () => void
  redo: () => void
}

export function useEdit(projectId: string): Edit {
  const [doc, setDocState] = useState<EditDoc | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [depth, setDepth] = useState({ past: 0, future: 0 })

  /* The document is mirrored into a ref so edits can be computed outside a
     setState updater. Updaters must stay pure -- React is free to run them more
     than once, and saving or pushing history from inside one duplicates both. */
  const current = useRef<EditDoc | null>(null)
  const past = useRef<EditDoc[]>([])
  const future = useRef<EditDoc[]>([])
  const lastTag = useRef<{ tag: string; at: number } | null>(null)
  const saveTimer = useRef<number | undefined>(undefined)

  const setDoc = useCallback((next: EditDoc) => {
    current.current = next
    setDocState(next)
  }, [])

  useEffect(() => {
    api.getProject(projectId)
      .then((p) => {
        past.current = []
        future.current = []
        lastTag.current = null
        setDepth({ past: 0, future: 0 })
        current.current = p.doc
        setDocState(p.doc)
      })
      .catch((e) => setError(e.message))
  }, [projectId])

  useEffect(() => () => window.clearTimeout(saveTimer.current), [])

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

  /** Record the pre-edit document unless this edit continues the last one. */
  const remember = useCallback((prev: EditDoc, tag?: string) => {
    const now = Date.now()
    const continues = tag
      && lastTag.current?.tag === tag
      && now - lastTag.current.at < COALESCE_MS
    if (!continues) {
      past.current = [...past.current, prev].slice(-LIMIT)
      future.current = []
    }
    lastTag.current = tag ? { tag, at: now } : null
    setDepth({ past: past.current.length, future: future.current.length })
  }, [])

  const commit = useCallback((next: EditDoc, tag?: string) => {
    const prev = current.current
    if (!prev) return
    remember(prev, tag)
    setDoc(next)
    save(next)
  }, [remember, setDoc, save])

  const patchOverlay = useCallback(
    (id: string, patch: Partial<TextOverlay>, tag?: string) => {
      const prev = current.current
      if (!prev) return
      commit({
        ...prev,
        overlays: prev.overlays.map((o) => (o.id === id ? { ...o, ...patch } : o)),
      }, tag ? `${id}:${tag}` : undefined)
    }, [commit])

  const addOverlay = useCallback((o: TextOverlay) => {
    const prev = current.current
    if (!prev) return
    commit({ ...prev, overlays: [...prev.overlays, o] })
    setSelected(o.id)
  }, [commit])

  const removeOverlay = useCallback((id: string) => {
    const prev = current.current
    if (!prev) return
    commit({ ...prev, overlays: prev.overlays.filter((o) => o.id !== id) })
    setSelected((s) => (s === id ? null : s))
  }, [commit])

  const undo = useCallback(() => {
    const prev = current.current
    const previous = past.current.at(-1)
    if (!prev || previous === undefined) return
    past.current = past.current.slice(0, -1)
    future.current = [prev, ...future.current].slice(0, LIMIT)
    lastTag.current = null
    setDepth({ past: past.current.length, future: future.current.length })
    setDoc(previous)
    save(previous)
  }, [setDoc, save])

  const redo = useCallback(() => {
    const prev = current.current
    const next = future.current[0]
    if (!prev || next === undefined) return
    future.current = future.current.slice(1)
    past.current = [...past.current, prev].slice(-LIMIT)
    lastTag.current = null
    setDepth({ past: past.current.length, future: future.current.length })
    setDoc(next)
    save(next)
  }, [setDoc, save])

  return {
    doc, selected, saving, error,
    canUndo: depth.past > 0,
    canRedo: depth.future > 0,
    select: setSelected,
    update: commit,
    patchOverlay, addOverlay, removeOverlay, undo, redo,
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
