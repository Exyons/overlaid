"""Burn a name / roll number / department card onto a video.

A thin client of `core/`. The web UI drives the same compiler through the same
edit document, so the CLI and the UI cannot render differently.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.compile import PRESETS, plan_render
from core.doc import DEFAULT_FONT, Box, DocError, EditDoc, Output, TextOverlay
from core.probe import ProbeError, probe
from core.run import RenderError, run, workdir

MARGIN = 0.025          # gap from the frame edge, as a fraction of height
POSITIONS = ("bottom-right", "bottom-left", "top-left", "top-right")


def parse_size(spec: str) -> tuple[int, int]:
    """Parse a WxH resolution."""
    try:
        w, h = (int(v) for v in spec.lower().split("x"))
    except ValueError:
        sys.exit(f"--normalize: expected WxH, got {spec!r}")
    if w <= 0 or h <= 0:
        sys.exit(f"--normalize: dimensions must be positive: {spec!r}")
    if w % 2 or h % 2:
        sys.exit(f"--normalize: yuv420p needs even dimensions: {spec!r}")
    return w, h


def corner_anchor(pos: str, out: Output, size: float,
                  box: Box | None) -> tuple[float, float]:
    """Place a corner-anchored overlay, leaving room for the plate's border.

    boxborderw grows the plate outward from the text, so the margin has to
    absorb it or the rectangle bleeds off the frame edge.
    """
    pad_h = (size * box.pad) if box else 0.0
    pad_w = pad_h * out.height / out.width
    v, h = pos.split("-")
    x = MARGIN + pad_w if h == "left" else 1.0 - MARGIN - pad_w
    y = MARGIN + pad_h if v == "top" else 1.0 - MARGIN - pad_h
    return x, y


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path)
    p.add_argument("-o", "--output", type=Path, help="default: <input>_tagged.<ext>")
    p.add_argument("--name", required=True)
    p.add_argument("--roll", required=True)
    p.add_argument("--dept", required=True)
    p.add_argument("--pos", default="bottom-right", choices=POSITIONS)
    p.add_argument("--font", default=DEFAULT_FONT)
    p.add_argument("--size", type=float, default=3.0,
                   help="text height as %% of video height (default: 3.0)")
    p.add_argument("--no-box", action="store_true",
                   help="drop the dark plate behind the text")
    p.add_argument("--format", default="mp4", choices=sorted(PRESETS))
    p.add_argument("--quality", type=int, default=60,
                   help="0-100, mapped onto the codec's own scale (default: 60)")
    p.add_argument("--normalize", nargs="?", const="1920x1080", default=None,
                   metavar="WxH",
                   help="letterbox to a standard resolution (default: 1920x1080). "
                        "Capture tools emit odd sizes that some portals reject.")
    a = p.parse_args()

    if not a.input.exists():
        sys.exit(f"no such file: {a.input}")

    try:
        source, has_audio = probe(a.input)
    except ProbeError as e:
        sys.exit(str(e))

    preset = PRESETS[a.format]
    out_dims = parse_size(a.normalize) if a.normalize else (source.width, source.height)
    output = Output(*out_dims)
    size = a.size / 100
    box = None if a.no_box else Box()
    x, y = corner_anchor(a.pos, output, size, box)

    doc = EditDoc(
        source=source,
        output=output,
        overlays=[TextOverlay(
            id="card",
            text="\n".join([a.name, a.roll, a.dept]),
            x=x, y=y, anchor=a.pos, size=size, font=a.font, box=box,
        )],
    )

    dst = a.output or a.input.with_name(f"{a.input.stem}_tagged{preset.suffix}")
    if preset.warn:
        print(f"note: {preset.warn}")

    try:
        plan = plan_render(doc, a.input, dst, workdir(),
                           preset=a.format, quality=a.quality,
                           has_audio=has_audio)
    except DocError as e:
        sys.exit(str(e))

    width = 40
    def bar(f: float) -> None:
        done = int(f * width)
        print(f"\r  [{'#' * done}{'.' * (width - done)}] {f:4.0%}", end="", flush=True)

    try:
        run(plan, total=doc.duration, on_progress=bar)
    except RenderError as e:
        print()
        sys.exit(f"render failed:\n{e}")
    print(f"\nwrote {dst}")


if __name__ == "__main__":
    main()
