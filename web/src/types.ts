// Mirrors core/doc.py. Geometry is normalised: crop is a fraction of the
// source, overlay position and size are fractions of the output.

export type Anchor =
  | 'top-left' | 'top-center' | 'top-right'
  | 'middle-left' | 'middle-center' | 'middle-right'
  | 'bottom-left' | 'bottom-center' | 'bottom-right'

export interface Source {
  width: number
  height: number
  fps: number
  duration: number
  /** Bits per second of the source video, 0 if the container does not say. */
  bitrate: number
}
export interface Trim { start: number; end: number | null }
export interface Crop { x: number; y: number; w: number; h: number }
export interface Output { width: number; height: number; fit: 'letterbox' | 'stretch' | 'cover' }
export interface Box { color: string; alpha: number; pad: number }

export interface TextOverlay {
  id: string
  type: 'text'
  text: string
  x: number
  y: number
  anchor: Anchor
  size: number
  font: string
  color: string
  box: Box | null
  line_gap: number
  start: number | null
  end: number | null
}

export interface EditDoc {
  version: number
  source: Source
  output: Output
  trim: Trim
  crop: Crop
  overlays: TextOverlay[]
  /** Playback rate. 2 plays twice as fast and halves the output duration. */
  speed: number
}

export interface Project {
  id: string
  name: string
  created_at: number
  updated_at: number
  has_audio: boolean
  doc: EditDoc
}

export interface Preset {
  name: string
  suffix: string
  warn: string | null
  has_quality: boolean
}

export interface Render {
  id: string
  project_id: string
  preset: string
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: number
  error: string | null
  created_at: number
  encoder: string | null
  size: number | null
  ready: boolean
}

export interface EncoderInfo {
  name: string
  label: string
  kind: 'cpu' | 'gpu'
}
