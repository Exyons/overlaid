/** SMPTE timecode. Post-production counts frames, not decimal seconds. */
export function timecode(seconds: number, fps: number): string {
  const safe = Math.max(0, seconds)
  const rate = fps > 0 ? fps : 25
  const total = Math.floor(safe * rate)
  const f = total % Math.round(rate)
  const s = Math.floor(safe) % 60
  const m = Math.floor(safe / 60) % 60
  const h = Math.floor(safe / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(s)}:${pad(f)}`
}

/** Shorter form for lists, where hours are almost always zero. */
export function duration(seconds: number): string {
  const s = Math.floor(seconds % 60)
  const m = Math.floor(seconds / 60) % 60
  const h = Math.floor(seconds / 3600)
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

export function fileSize(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes, i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n < 10 && i > 0 ? n.toFixed(1) : Math.round(n)} ${units[i]}`
}
