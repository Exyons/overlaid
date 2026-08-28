import type { ReactNode } from 'react'
import { Inspector } from './Inspector'
import type { EditDoc, TextOverlay } from './types'

/**
 * The effects tab.
 *
 * Text is the only effect so far, but it is presented as one group among
 * several rather than as the whole tab, so adding blur, zoom or a highlight
 * later is a matter of another group rather than a rearrangement.
 */
export function EffectsPanel({
  doc, selected, onSelect, onAdd, onPatch, onRemove,
}: {
  doc: EditDoc
  selected: string | null
  onSelect: (id: string | null) => void
  onAdd: () => void
  onPatch: (patch: Partial<TextOverlay>, tag?: string) => void
  onRemove: () => void
}) {
  const chosen = doc.overlays.find((o) => o.id === selected) ?? null

  return (
    <div className="effects">
      <EffectGroup
        name="Text"
        count={doc.overlays.length}
        action={<button onClick={onAdd}>Add text</button>}
      >
        {doc.overlays.length === 0 ? (
          <p className="nothing">
            No text yet. Add one and drag it onto the picture.
          </p>
        ) : (
          <ul className="effect-list">
            {doc.overlays.map((o) => (
              <li key={o.id}>
                <button
                  className={o.id === selected ? 'on' : ''}
                  aria-pressed={o.id === selected}
                  onClick={() => onSelect(o.id === selected ? null : o.id)}
                >
                  {firstLine(o.text)}
                </button>
              </li>
            ))}
          </ul>
        )}

        {chosen && (
          <Inspector
            overlay={chosen}
            outputWidth={doc.output.width}
            outputHeight={doc.output.height}
            onPatch={onPatch}
            onRemove={onRemove}
          />
        )}
      </EffectGroup>
    </div>
  )
}

function EffectGroup({
  name, count, action, children,
}: {
  name: string
  count: number
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="effect-group">
      <header className="panel-head">
        <span className="label">
          {name}{count > 0 && <span className="value mono"> {count}</span>}
        </span>
        {action}
      </header>
      {children}
    </section>
  )
}

/** Enough of the text to recognise the block by, on one line. */
function firstLine(text: string): string {
  const line = text.split('\n')[0].trim()
  if (!line) return 'Empty'
  return line.length > 28 ? `${line.slice(0, 27)}…` : line
}
