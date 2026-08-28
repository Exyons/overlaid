# video-editing

Burns a name / roll number / department card onto a video, plus trim, crop,
resize and format conversion. CLI today; a browser UI is being built on the
same core.

## Run

```bash
uv run python overlay.py INPUT.mp4 \
  --name "Your Name" \
  --roll "21BCE1234" \
  --dept "Computer Science & Engineering"
```

Writes `INPUT_tagged.mp4` beside the input unless `-o` says otherwise.

## Options

| Flag | Default | Notes |
|---|---|---|
| `--pos` | `bottom-right` | also `bottom-left`, `top-left`, `top-right` |
| `--size` | `3.0` | text height as a % of video height, so it scales with resolution |
| `--no-box` | off | drops the dark plate behind the text |
| `--font` | DejaVu Sans Bold | any TTF path |
| `--format` | `mp4` | `mp4`, `webm`, `gif`, `mov` |
| `--quality` | `60` | 0-100, mapped onto each codec's own scale |
| `--normalize` | off | letterbox to `1920x1080`, or pass `WxH` |
| `-o` | — | output path |

## --normalize

Capture tools emit odd frame sizes — this repo was built against an 1856x1116
OBS recording — and some upload portals reject anything non-standard. This
scales to fit and pads the remainder black, so the aspect ratio survives instead
of being squeezed. Text is drawn after the pad, so it never lands in a bar.

## Browser UI

```bash
./run.sh build     # compile the frontend once
./run.sh serve     # http://127.0.0.1:8787
```

For development, `./run.sh dev` runs FastAPI with reload on 8787 and Vite on
5173, with `/api` proxied across. Set `PORT` to move the backend.

Upload a video, add text, drag it where you want it, and export.

Every time you stop moving, the viewer fetches a real frame from the renderer
and swaps it in. The matte around the picture and the readout by the transport
say which you are looking at: amber while it is the browser's approximation,
cyan once the renderer has confirmed it. The two are drawn from the same filter
chain, so a frame marked rendered is what the export will contain.

Preview requests carry the document the editor currently holds rather than
whatever autosave last persisted, so the picture can never lag the controls.

| Key | Does |
|---|---|
| drag | move a text block |
| Left / Right | step one frame; hold Shift for ten |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo |
| `Delete` | remove the selected text |
| `Esc` | deselect |

## Layout

```
core/
  doc.py        the edit document: dataclasses, JSON, validation
  compile.py    EditDoc -> ffmpeg argv.  Pure: no subprocess, no I/O
  probe.py      ffprobe wrapper
  run.py        executes a compiled plan, reports progress
overlay.py      CLI, a thin client of core/
api/
  main.py       routes
  db.py         sqlite3: projects + renders
  jobs.py       background render queue
web/            Vite + React + TS
  src/
    Library.tsx   upload, project list
    Viewer.tsx    player, scrubber, proof state
    Canvas.tsx    overlay drawing, drag, hit-testing
    Inspector.tsx text, font, size, anchor, plate
    Export.tsx    format, quality, progress, download
    layout.ts     canvas geometry, mirrors compile.py
    store.ts      edit document, undo/redo, autosave
data/           uploads, renders, sqlite (gitignored)
```

`compile.py` is deliberately pure — it takes a document and returns a plan. That
is what lets the whole filter chain be tested as a string, and what will let the
browser preview and the final export share one code path rather than two that
drift.

`web/src/layout.ts` deliberately mirrors `drawtext_filter()` in
`core/compile.py`. The canvas is sized to the output resolution and scaled down
with CSS, so both work in the same coordinate space and a click lands on the
pixel the renderer will draw. Where those two files disagree, the preview lies.

Design notes: `docs/superpowers/specs/2026-08-28-video-editor-design.md`

## Notes

Text is passed to ffmpeg through a sidecar file, not inline on the command line.
Inline text has to survive two layers of ffmpeg parsing, and no escaping scheme
handles apostrophes, `%` and backslashes together — all three turn up in real
names and department strings.

## Tests

```bash
uv run pytest
```

Most of the suite asserts on compiled filter strings and needs no ffmpeg. A
handful render a committed two-second fixture for real and probe the result.
