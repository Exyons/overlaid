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

### Crop, trim, size

The right-hand panel has three tabs. **Effects** holds the text blocks, listed
so one can be picked without hunting for it on the picture; it is a group of
effects rather than a text panel, so further effects join it rather than
displace it. **Crop & size** opens the crop tool: the
picture switches to the whole uncropped frame with a rectangle over it, since
choosing a crop means looking at the part you are about to throw away. Drag the
rectangle or its handles; pick a shape (16:9, 1:1, 9:16 and so on) to constrain
it. Releasing the rectangle reshapes the output to match, because cropping
changes the shape of the picture -- leaving the old size would letterbox the new
crop back into the frame it was cut from. Output height and fit are next to it
if you want something else.

Trim handles sit on the scrubber. The bar always spans the whole source and the
excluded parts are dimmed rather than removed: trimming is non-destructive, so
the material outside the range still exists and stays reachable.

| Key | Does |
|---|---|
| `Space` | play / pause |
| drag | move a text block |
| Left / Right | step one frame; hold Shift for ten |
| `Ctrl+Z` / `Ctrl+Shift+Z` | undo / redo |
| `Delete` | remove the selected text |
| `Esc` | deselect |

The nine-cell control snaps text to a part of the frame and anchors it there, so
the text grows inward and a longer line cannot push itself off the edge. Drag
for anywhere else; the control then reads "custom" rather than claiming a corner
the text is no longer in.

## Export

Quality is a 0-100 slider mapped into the *usable* part of each codec's scale,
not the whole of it. 100 means visually lossless (H.264 CRF 16), not
mathematically lossless: CRF 0 reproduces the source's own compression
artefacts exactly and measured 7.7x the size of a 12 Mb/s screen capture. The
slider's floor stops where the picture is still worth looking at.

A quality target alone does not bound a file, so the bitrate is also capped
against the material: the source's own rate, scaled by how much of its picture
survives. Cropping and downscaling lower the cap proportionally. Upscaling does
not raise it -- more output pixels than the source holds cannot mean more
detail, so they must not mean more bits. Two things had been exploiting the
absence of a cap, measured on a 12.3 Mb/s screen capture:

| | Bitrate |
|---|---|
| 3.5x upscale, libx264 | 20.4 Mb/s |
| native size, libx264 | 8.6 Mb/s |
| native size, NVENC | 19.4 Mb/s |
| **the same three, capped** | **4.5-5.2 Mb/s** |

Hardware encoders were the worse offender: given a quality target and no
ceiling, NVENC produced 2.4x the size of libx264 at a matched setting. The
output sizes offered never exceed what the crop actually contains, for the same
reason.

## Speed

Speed sits with the trim controls, since both change how long the export runs.
Speeding up resamples back to the source frame rate rather than leaving twice as
many frames per second -- at 2x that would cost bitrate for motion nobody can
see. Audio is retimed with `atempo`, chained into stages when the rate falls
outside the 0.5-2 that one stage accepts.

H.264 exports use hardware encoding when the machine has it. Encoders are found
by probing -- a real one-frame encode -- rather than by reading
`ffmpeg -encoders`, which lists what the binary supports rather than what the
hardware will accept. A laptop with a switchable NVIDIA card advertises NVENC
and then fails at CUDA init; VAAPI will bind to a render node whose driver
cannot encode. Anything that fails its probe is not offered, and an encoder that
stops working falls back to libx264 rather than failing the export.

Measured on a 70s 1856x1116 60fps capture:

| | Time | Size |
|---|---|---|
| Quick Sync, quality 75 | 21s | 55 MB |
| Quick Sync, quality 100 | 20s | 92 MB |
| libx264, quality 100 | 63s | 78 MB |

Hardware is several times faster; libx264 spends longer and fits more picture
into the same bitrate.

## Finding the crop

**Crop & size** has a *Detect content* button. Screen captures put a lot of
still furniture -- tabs, a URL bar, a settings panel -- around the part worth
keeping, and what moves is a good proxy for that without needing to recognise
any of it. Frames are sampled from windows spread across the recording and the
per-pixel variation over time is thresholded: the furniture scores near zero,
the content does not.

It proposes rather than applies, and says when it found nothing rather than
returning a confident rectangle around noise. On the recording this was built
against it lands within a few percent of a hand-made crop, and additionally
keeps the app's own toolbar -- those readouts animate, so they are genuinely
part of what moves.

Sampling windows rather than the whole timeline is what makes it quick: an
`fps` filter decodes every frame in the file to keep a few dozen, measuring
8.4s on a three-minute capture against 1.7s for the same frames taken from
eight half-second windows. Hardware decode is slower still, not faster --
frames have to come back to system memory for the analysis either way.

## Layout

```
core/
  analyze.py    reads the footage and proposes edits (OpenCV)
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

Preview frames are PNG, not JPEG. A JPEG decoder assumes BT.601 full range
whatever the file says, while this footage is BT.709 limited range and the
browser decodes the video element as such -- so the rendered frame and the
video it replaced drew in visibly different colours, worst in green, and every
edit flashed between them. Measured against a direct conversion, the mean
per-pixel error went from 3.37 to 0.067 by dropping the YCbCr round trip. RGB
has no matrix to disagree about. Library thumbnails are scaled down first,
since a full-size lossless frame per row would be several megabytes each.

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
