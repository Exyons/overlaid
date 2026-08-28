import { cropSize } from './CropBox'
import type { Crop, EditDoc, Output } from './types'

export const FULL_FRAME: Crop = { x: 0, y: 0, w: 1, h: 1 }

/** Aspect presets, as width / height of the finished picture. */
export const ASPECTS: { label: string; value: number | null }[] = [
  { label: 'Free', value: null },
  { label: '16:9', value: 16 / 9 },
  { label: '4:3', value: 4 / 3 },
  { label: '1:1', value: 1 },
  { label: '4:5', value: 4 / 5 },
  { label: '9:16', value: 9 / 16 },
]

/** Common output heights. Width follows from the aspect being produced.
 *  Only those at or below what the crop actually contains are offered:
 *  upscaling invents no detail but costs bitrate for the pixels it invents. */
const HEIGHTS = [2160, 1440, 1080, 720, 480]

const FITS: { value: Output['fit']; label: string; note: string }[] = [
  { value: 'letterbox', label: 'Fit', note: 'Whole picture, bars where it does not fill.' },
  { value: 'cover', label: 'Fill', note: 'Fills the frame, trimming the overflow.' },
  { value: 'stretch', label: 'Stretch', note: 'Distorts to fit exactly. Rarely what you want.' },
]

const even = (n: number) => Math.max(2, Math.round(n) & ~1)

/** Output size that matches what the crop produces, at a chosen height.
 *
 *  Capped at the crop's own height. Asking for more pixels than the material
 *  holds cannot add detail, and the encoder then spends real bitrate on the
 *  invented ones -- a 3.5x upscale measured 2.4x the file size for no more
 *  picture than the 1x version. */
export function outputForCrop(doc: EditDoc, height?: number): Output {
  const [cw, ch] = cropSize(doc.crop, doc.source)
  const h = Math.min(height ?? ch, ch)
  return { width: even((h * cw) / ch), height: even(h), fit: doc.output.fit }
}

export function FramePanel({
  doc, aspect, onAspect, onCrop, onOutput, onReset,
}: {
  doc: EditDoc
  aspect: number | null
  onAspect: (a: number | null) => void
  onCrop: (crop: Crop, tag?: string) => void
  onOutput: (output: Output) => void
  onReset: () => void
}) {
  const [cw, ch] = cropSize(doc.crop, doc.source)
  const cropped = doc.crop.w < 1 || doc.crop.h < 1
  const out = doc.output
  const sameShape = Math.abs(cw / ch - out.width / out.height) < 0.01
  const upscaling = out.width * out.height > cw * ch * 1.02
  // The crop's own height is always offered, plus every standard size below it.
  const heights = [...new Set([ch, ...HEIGHTS.filter((h) => h < ch)])]
    .sort((a, b) => b - a)

  function pickAspect(value: number | null) {
    onAspect(value)
    if (value === null) return
    // Reshape the current crop around its centre so the choice takes effect
    // immediately rather than waiting for the next drag.
    const { source } = doc
    let w = doc.crop.w
    let h = (w * source.width) / (value * source.height)
    if (h > 1) { h = 1; w = (h * source.height * value) / source.width }
    const x = Math.min(Math.max(0, doc.crop.x + (doc.crop.w - w) / 2), 1 - w)
    const y = Math.min(Math.max(0, doc.crop.y + (doc.crop.h - h) / 2), 1 - h)
    onCrop({ x, y, w, h })
  }

  return (
    <section className="frame-panel">
      <div className="field">
        <span className="label">Shape</span>
        <div className="chips">
          {ASPECTS.map((a) => (
            <button
              key={a.label}
              className={a.value === aspect ? 'on' : ''}
              aria-pressed={a.value === aspect}
              onClick={() => pickAspect(a.value)}
            >
              {a.label}
            </button>
          ))}
        </div>
        <p className="note">Drag the rectangle on the picture to choose the area.</p>
      </div>

      <div className="field">
        <span className="label">
          Crop <span className="value mono">{cw}&times;{ch}</span>
        </span>
        <button className="wide" onClick={onReset} disabled={!cropped}>
          Reset to full frame
        </button>
      </div>

      <div className="field">
        <label className="label" htmlFor="fr-height">
          Output <span className="value mono">{out.width}&times;{out.height}</span>
        </label>
        <select
          id="fr-height"
          value={heights.includes(out.height) ? out.height : ''}
          onChange={(e) => onOutput(outputForCrop(doc, Number(e.target.value)))}
        >
          {!heights.includes(out.height) && (
            <option value="">{out.height}p (current)</option>
          )}
          {heights.map((h) => (
            <option key={h} value={h}>
              {h}p{h === ch ? ' — full detail' : ''}
            </option>
          ))}
        </select>
        {upscaling && (
          <p className="note warn-note">
            Larger than the {cw}&times;{ch} the crop contains, so the extra
            pixels are invented and cost bitrate for no more picture.
          </p>
        )}
        {!sameShape && (
          <button
            className="wide"
            onClick={() => onOutput(outputForCrop(doc, out.height))}
          >
            Match output to crop
          </button>
        )}
      </div>

      <div className="field">
        <span className="label">When shapes differ</span>
        <div className="chips">
          {FITS.map((f) => (
            <button
              key={f.value}
              className={f.value === out.fit ? 'on' : ''}
              aria-pressed={f.value === out.fit}
              onClick={() => onOutput({ ...out, fit: f.value })}
            >
              {f.label}
            </button>
          ))}
        </div>
        <p className="note">{FITS.find((f) => f.value === out.fit)?.note}</p>
      </div>
    </section>
  )
}
