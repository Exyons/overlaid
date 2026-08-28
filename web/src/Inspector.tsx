import { useFonts } from './fonts'
import type { Anchor, TextOverlay } from './types'

const ANCHORS: Anchor[] = [
  'top-left', 'top-center', 'top-right',
  'middle-left', 'middle-center', 'middle-right',
  'bottom-left', 'bottom-center', 'bottom-right',
]

export function Inspector({
  overlay, onPatch, onRemove, outputHeight,
}: {
  overlay: TextOverlay | null
  onPatch: (patch: Partial<TextOverlay>, tag?: string) => void
  onRemove: () => void
  outputHeight: number
}) {
  const fonts = useFonts()

  if (!overlay) {
    return (
      <aside className="inspector">
        <p className="nothing">
          Select a text block to edit it, or add one to get started.
        </p>
      </aside>
    )
  }

  const o = overlay
  return (
    <aside className="inspector">
      <div className="field">
        <label className="label" htmlFor="ov-text">Text</label>
        <textarea
          id="ov-text"
          value={o.text}
          rows={3}
          spellCheck={false}
          onChange={(e) => onPatch({ text: e.target.value }, 'text')}
        />
        <p className="note">Each line becomes a line in the video.</p>
      </div>

      <div className="field">
        <label className="label" htmlFor="ov-font">Font</label>
        <select
          id="ov-font"
          value={o.font}
          onChange={(e) => onPatch({ font: e.target.value })}
        >
          {fonts.some((f) => f.path === o.font) ? null : (
            <option value={o.font}>{o.font}</option>
          )}
          {fonts.map((f) => (
            <option key={f.id} value={f.path}>{f.label}</option>
          ))}
        </select>
      </div>

      <div className="field">
        <label className="label" htmlFor="ov-size">
          Size <span className="value">{Math.round(o.size * outputHeight)} px</span>
        </label>
        <input
          id="ov-size" type="range" min={0.01} max={0.2} step={0.002}
          value={o.size}
          onChange={(e) => onPatch({ size: Number(e.target.value) }, 'size')}
        />
        <p className="note">Set as a share of frame height, so it survives a resize.</p>
      </div>

      <div className="field">
        <span className="label">Anchor</span>
        <div className="anchor-grid" role="group" aria-label="Anchor">
          {ANCHORS.map((a) => (
            <button
              key={a}
              className={a === o.anchor ? 'on' : ''}
              aria-label={a.replace('-', ' ')}
              aria-pressed={a === o.anchor}
              onClick={() => onPatch({ anchor: a })}
            />
          ))}
        </div>
        <p className="note">
          Text grows away from its anchor, so a longer line cannot run off frame.
        </p>
      </div>

      <div className="field row">
        <div>
          <label className="label" htmlFor="ov-color">Colour</label>
          <input
            id="ov-color" type="color" value={o.color}
            onChange={(e) => onPatch({ color: e.target.value }, 'color')}
          />
        </div>
        <div>
          <span className="label">Plate</span>
          <label className="check">
            <input
              type="checkbox" checked={o.box !== null}
              onChange={(e) => onPatch({
                box: e.target.checked
                  ? { color: '#000000', alpha: 0.55, pad: 0.5 }
                  : null,
              })}
            />
            <span>Behind text</span>
          </label>
        </div>
      </div>

      {o.box && (
        <div className="field">
          <label className="label" htmlFor="ov-alpha">
            Plate opacity <span className="value">{Math.round(o.box.alpha * 100)}%</span>
          </label>
          <input
            id="ov-alpha" type="range" min={0} max={1} step={0.05}
            value={o.box.alpha}
            onChange={(e) => onPatch(
              { box: { ...o.box!, alpha: Number(e.target.value) } }, 'alpha')}
          />
        </div>
      )}

      <button className="remove" onClick={onRemove}>Delete text</button>
    </aside>
  )
}
