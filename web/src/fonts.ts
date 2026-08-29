import { useEffect, useState } from 'react'

export interface FontInfo {
  id: string
  family: string
  style: string
  label: string
  path: string
}

/** Faces already handed to the browser, so a font is fetched at most once. */
const loaded = new Map<string, Promise<string>>()

/** A CSS family name unique to one font file. One family name can cover several
 *  weights, and the canvas must draw the exact face ffmpeg will use. */
function familyFor(font: FontInfo): string {
  return `ol-${font.id}`
}

export function loadFont(font: FontInfo): Promise<string> {
  const family = familyFor(font)
  let pending = loaded.get(family)
  if (!pending) {
    pending = new FontFace(family, `url(/api/fonts/${font.id}/file)`)
      .load()
      .then((face) => {
        document.fonts.add(face)
        return family
      })
      .catch((e) => {
        // A failed load must not stay in the cache: the entry is what stops a
        // second attempt, so a font that 404s once would never load again
        // without a page reload.
        loaded.delete(family)
        throw e
      })
    loaded.set(family, pending)
  }
  return pending
}

/** The font catalogue, fetched once per session rather than per component. */
let catalogue: Promise<FontInfo[]> | null = null

export function useFonts(): FontInfo[] {
  const [fonts, setFonts] = useState<FontInfo[]>([])
  useEffect(() => {
    catalogue ??= fetch('/api/fonts').then((r) => r.json())
    catalogue.then(setFonts).catch(() => setFonts([]))
  }, [])
  return fonts
}

/** Load every face a document references, keyed by the path stored in the doc.
 *  Until a face resolves the canvas falls back to a system font, which measures
 *  differently, so text can shift slightly on first paint and then settle. */
export function useLoadedFonts(paths: string[]): Record<string, string> {
  const fonts = useFonts()
  const [families, setFamilies] = useState<Record<string, string>>({})
  const key = paths.join(' ')

  useEffect(() => {
    let live = true
    const wanted = fonts.filter((f) => paths.includes(f.path))
    Promise.all(
      wanted.map((f) => loadFont(f).then((fam) => [f.path, fam] as const)),
    )
      .then((pairs) => { if (live) setFamilies(Object.fromEntries(pairs)) })
      .catch(() => {})
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fonts, key])

  return families
}
