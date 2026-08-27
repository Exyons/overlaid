# Browser video editor — design

Date: 2026-08-28
Status: approved, phase 0 in progress

## Goal

A local web UI for tagging and trimming screen-capture videos. Replaces the
`overlay.py` CLI for everyday use, and doubles as a portfolio piece.

Not a general NLE. No multi-track compositing, no transitions, no audio editing.

## Scope

Four slices, built in order. Each is usable before the next starts.

| Slice | Contents |
|---|---|
| D — shell | upload, project list, frame preview, render queue |
| A — text | click-to-place overlays, drag, inspector, undo/redo |
| B — timeline | trim, crop, resize, export presets |
| C — CV | detection, tracking, dynamic overlays. **Deferred**, re-brainstormed separately |

## Decisions

**Hybrid preview.** Dragging is drawn on a browser canvas for zero-latency feel;
on release the client requests a real ffmpeg frame and swaps it in. The browser
render is an approximation used only while the mouse is down. Every committed
state is verified against the real renderer.

**One renderer.** `core/compile.py` turns an edit document into ffmpeg arguments.
The CLI, the frame preview, and the final export all call it. There is no second
code path that could drift from the first. This is what makes the preview
trustworthy — not discipline, but structure.

**Normalized geometry.** No pixel coordinates are ever stored. Crop is a fraction
of the source; overlay position and font size are fractions of the output. Change
export resolution and the layout is proportionally identical.

**Corner anchors.** An overlay's position is its anchor point, not its top-left
origin. Right-anchored text grows leftward, so lengthening the text cannot push
it off the frame.

**Vite + React + TS.** An editor is a state machine — overlay list, selection,
undo/redo, playhead, job status. Next.js was considered and rejected: every
component here is client-side, so SSR and RSC are dead weight, and its API routes
invite splitting render logic across two languages.

**SQLite.** Uploaded media needs server-side storage regardless; a project row
gives those files an owner, a lifecycle, and a cleanup story. stdlib `sqlite3`,
no ORM.

## Layout

```
core/
  doc.py        EditDoc dataclasses, JSON (de)serialisation, validation
  compile.py    EditDoc -> ffmpeg argv.  Pure function. No subprocess, no I/O
  probe.py      ffprobe wrapper
  run.py        executes compiled argv, parses -progress output
api/
  main.py       FastAPI routes
  db.py         sqlite3, projects + renders
  jobs.py       background queue, SSE progress
web/            Vite + React + TS
overlay.py      CLI, thin client of core/
tests/
```

## Edit document

```json
{
  "version": 1,
  "source":  { "width": 1856, "height": 1116, "fps": 60, "duration": 70.65 },
  "trim":    { "start": 5.0, "end": 42.0 },
  "crop":    { "x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0 },
  "output":  { "width": 1920, "height": 1080, "fit": "letterbox" },
  "overlays": [
    { "id": "o1", "type": "text", "text": "Name\nRoll\nDept",
      "x": 0.97, "y": 0.94, "anchor": "bottom-right",
      "size": 0.030, "font": "DejaVuSans-Bold", "color": "#ffffff",
      "box": { "color": "#000000", "alpha": 0.55, "pad": 0.5 },
      "start": null, "end": null }
  ]
}
```

`start`/`end` are null for "whole clip". They exist from day one so slice C's
time-bounded overlays need no schema migration. `version` gates future migrations.

Overlay text is multiline: ffmpeg's `drawtext` renders embedded newlines as one
block under a single backing plate, and `th` resolves to the whole block's
height, so the anchor math is unchanged. This replaces the CLI's three stacked
`drawtext` calls and their ragged per-line plates.

## Section 3 — the compiler

`compile.py` is the heart. Order of operations is fixed and matters:

```
trim   -> input seek        -ss / -to before -i
crop   -> crop=iw*w:ih*h:iw*x:ih*y      operates on SOURCE pixels
scale  -> scale=fw:fh:flags=lanczos     fitted inside output
pad    -> pad=W:H:(ow-iw)/2:(oh-ih)/2   produces the OUTPUT canvas
text   -> drawtext                      placed on the OUTPUT canvas
```

Text is applied last, after padding, which is why overlay coordinates are
normalized against output rather than source dimensions — the text must be
positionable in the letterbox bars, and must not move when the source aspect
changes.

Anchor resolution, where `(ax, ay)` is the normalized anchor point:

| Anchor part | drawtext x | drawtext y |
|---|---|---|
| left / top | `ax*W` | `ay*H` |
| center / middle | `ax*W-tw/2` | `ay*H-th/2` |
| right / bottom | `ax*W-tw` | `ay*H-th` |

Three entry points, one chain:

- `compile_render(doc, dst, preset)` — full export
- `compile_preview(doc, t, dst)` — same chain plus `-ss t -frames:v 1`
- `compile_probe(doc)` — dimensions only, no execution

Because `compile_preview` and `compile_render` build the same filter chain from
the same document, a frame the user approved is a frame the export reproduces.

## Export presets

| Preset | Args | Notes |
|---|---|---|
| mp4 | `libx264 -crf N -preset medium -pix_fmt yuv420p`, `aac` | default |
| webm | `libvpx-vp9 -crf N -b:v 0`, `libopus` | 5-10x slower; UI must warn |
| gif | two-pass `palettegen` / `paletteuse` | force fps<=15, width<=800 |
| mov | `prores_ks -profile:v 3`, `pcm_s16le` | ~1.5 GB/min; warn on size |

GIF is the only preset that is not a single ffmpeg invocation.

## Testing

`compile.py` is pure, so the bulk of the suite is fast and hermetic:

- **Golden tests** on the compiler — assert exact filter strings for known
  documents. Catches ordering and anchor-math regressions with no ffmpeg run.
- **Property tests** — for any output resolution, a normalized overlay stays
  within frame bounds; crop rects never exceed source.
- **Integration tests** — a committed 2-second fixture actually rendered, then
  ffprobed to assert dimensions, duration, and stream presence. A handful only.
- **Escaping tests** — `drawtext` special characters (`: ' \ %` and newline)
  survive a round trip. This is where injection bugs would live.

## Risks

- **Browser/ffmpeg text metric mismatch.** Canvas `fillText` and `drawtext` will
  not agree to the pixel. Mitigated by the confirm-on-release round trip, not by
  trying to make them match.
- **GIF file sizes.** Uncapped, a 70s 1080p60 export is hundreds of MB. The
  preset hard-caps fps and width rather than trusting the user.
- **Long renders blocking the API.** Renders run in a worker with progress
  streamed over SSE; the request returns immediately with a job id.
