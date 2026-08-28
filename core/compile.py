"""Turn an EditDoc into ffmpeg arguments.

This module is pure: it reads a document and returns a plan. It never spawns a
process, writes a file, or touches the clock. That is what makes the render
pipeline testable — the filter chain for any document can be asserted as a
string, with no ffmpeg installed and no fixtures on disk.

It is also the reason the preview can be trusted. `plan_preview` and
`plan_render` build their filter chain with the same function, so a frame the
user approved is a frame the export reproduces. The guarantee is structural,
not a matter of keeping two code paths in step by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import encoders
from .doc import Box, EditDoc, TextOverlay

# Text is passed to drawtext through a sidecar file rather than inline. Inline
# text has to survive two layers of ffmpeg parsing, and no escaping scheme
# handles apostrophes, '%' and backslashes together -- all three appear in
# ordinary names and department strings. expansion=none additionally stops
# drawtext treating '%' as a strftime directive.
TEXT_SUFFIX = ".txt"


@dataclass
class Plan:
    """A render that has been fully decided but not yet executed."""

    argv: list[str]
    textfiles: dict[Path, str] = field(default_factory=dict)
    #: Set when the format needs more than one ffmpeg invocation (GIF).
    second_pass: list[str] | None = None
    #: Which encoder was chosen, for reporting back to the user.
    encoder: str | None = None

    def materialise(self) -> None:
        """Write the sidecar text files this plan's argv refers to."""
        for path, content in self.textfiles.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")


# --- geometry --------------------------------------------------------------


def fit_inside(src: tuple[int, int], dst: tuple[int, int]) -> tuple[int, int]:
    """Largest even-dimensioned box with `src`'s aspect that fits inside `dst`."""
    sw, sh = src
    dw, dh = dst
    k = min(dw / sw, dh / sh)
    return int(sw * k) // 2 * 2, int(sh * k) // 2 * 2


def anchor_expr(anchor: str, x: float, y: float) -> tuple[str, str]:
    """Map a normalized anchor point to drawtext x/y expressions.

    `tw`/`th` are ffmpeg's text width and height, resolved at draw time -- which
    is why anchoring works for text whose width we do not know here.
    """
    v, h = anchor.split("-")
    ex = {
        "left": f"w*{x}",
        "center": f"w*{x}-tw/2",
        "right": f"w*{x}-tw",
    }[h]
    ey = {
        "top": f"h*{y}",
        "middle": f"h*{y}-th/2",
        "bottom": f"h*{y}-th",
    }[v]
    return ex, ey


# --- filter chain ----------------------------------------------------------


def crop_filter(doc: EditDoc) -> str | None:
    c = doc.crop
    if c.is_identity:
        return None
    # Expressed against iw/ih so the filter stays correct regardless of what
    # the decoder reports for this particular file.
    return f"crop=iw*{c.w}:ih*{c.h}:iw*{c.x}:ih*{c.y}"


def scale_filters(doc: EditDoc) -> list[str]:
    """Scale and pad the cropped source onto the output canvas."""
    out = doc.output
    cropped = (
        max(2, int(doc.source.width * doc.crop.w)),
        max(2, int(doc.source.height * doc.crop.h)),
    )
    if out.fit == "stretch":
        return [f"scale={out.width}:{out.height}:flags=lanczos"]
    if out.fit == "cover":
        # Fill the frame and trim the overflow rather than showing bars.
        return [
            f"scale={out.width}:{out.height}:force_original_aspect_ratio=increase"
            ":flags=lanczos",
            f"crop={out.width}:{out.height}",
        ]
    fw, fh = fit_inside(cropped, (out.width, out.height))
    if (fw, fh) == (out.width, out.height):
        return [f"scale={out.width}:{out.height}:flags=lanczos"]
    return [
        f"scale={fw}:{fh}:flags=lanczos",
        f"pad={out.width}:{out.height}:(ow-iw)/2:(oh-ih)/2:black",
    ]


def _colour(hex_colour: str, alpha: float | None = None) -> str:
    """ffmpeg accepts #rrggbb as 0xRRGGBB, with an optional @alpha suffix."""
    value = "0x" + hex_colour.lstrip("#")
    return f"{value}@{alpha}" if alpha is not None else value


def drawtext_filter(o: TextOverlay, doc: EditDoc, textfile: Path) -> str:
    """One drawtext call for one overlay.

    Multiline text is drawn as a single block under a single plate: ffmpeg
    resolves `th` to the height of all lines together, so the anchor maths is
    identical whether the overlay holds one line or five.
    """
    size_px = max(1, round(doc.output.height * o.size))
    ex, ey = anchor_expr(o.anchor, o.x, o.y)

    parts = [
        f"textfile='{textfile}'",
        "expansion=none",
        f"fontfile='{o.font}'",
        f"fontsize={size_px}",
        f"fontcolor={_colour(o.color)}",
        f"line_spacing={round(size_px * o.line_gap)}",
        f"x={ex}",
        f"y={ey}",
    ]
    if o.box is not None:
        parts += [
            "box=1",
            f"boxcolor={_colour(o.box.color, o.box.alpha)}",
            f"boxborderw={max(2, round(size_px * o.box.pad))}",
        ]
    if o.is_timed:
        # Times are relative to the trimmed clip, matching what the user scrubs.
        lo = o.start if o.start is not None else 0
        hi = o.end if o.end is not None else doc.duration
        parts.append(f"enable='between(t,{lo},{hi})'")
    return "drawtext=" + ":".join(parts)


def build_chain(doc: EditDoc, workdir: Path) -> tuple[str, dict[Path, str]]:
    """The complete -vf chain, plus the sidecar files it references.

    Order is load-bearing: crop reads source pixels, scale and pad build the
    output canvas, and text lands on that canvas last so it can sit anywhere on
    the final frame -- letterbox bars included.
    """
    chain: list[str] = []
    if (c := crop_filter(doc)) is not None:
        chain.append(c)
    chain += scale_filters(doc)
    if doc.speed != 1.0:
        # setpts alone would leave twice as many frames per second at 2x, which
        # costs bitrate for motion nobody can see. Resampling back to the source
        # rate drops the surplus instead.
        chain.append(f"setpts=PTS/{doc.speed}")
        chain.append(f"fps={doc.source.fps or 30:.4f}")

    textfiles: dict[Path, str] = {}
    for o in doc.overlays:
        path = workdir / f"{o.id}{TEXT_SUFFIX}"
        textfiles[path] = o.text
        chain.append(drawtext_filter(o, doc, path))

    return ",".join(chain), textfiles


# --- output presets --------------------------------------------------------


@dataclass(frozen=True)
class Preset:
    name: str
    suffix: str
    video: list[str]
    audio: list[str]
    #: GIF cannot be produced in one pass, and is enormous without these caps.
    max_fps: int | None = None
    max_width: int | None = None
    warn: str | None = None


PRESETS: dict[str, Preset] = {
    "mp4": Preset(
        "mp4", ".mp4",
        [],                                     # supplied by the chosen encoder
        ["-c:a", "aac", "-b:a", "192k"],
    ),
    "webm": Preset(
        "webm", ".webm",
        ["-c:v", "libvpx-vp9", "-b:v", "0", "-row-mt", "1"],
        ["-c:a", "libopus", "-b:a", "128k"],
        warn="VP9 encodes roughly 5-10x slower than H.264.",
    ),
    "gif": Preset(
        "gif", ".gif",
        [], [],
        max_fps=15, max_width=800,
        warn="Capped to 15 fps and 800px wide; GIF has no audio.",
    ),
    "mov": Preset(
        "mov", ".mov",
        ["-c:v", "prores_ks", "-profile:v", "3"],
        ["-c:a", "pcm_s16le"],
        warn="ProRes runs about 1.5 GB per minute at 1080p.",
    ),
}

# The quality slider is mapped into the usable part of each codec's scale, not
# the whole of it.
#
# H.264 CRF 0 is mathematically lossless, which is not what anyone means by
# "maximum quality": the source is already a lossy encode, so CRF 0 spends an
# enormous bitrate reproducing the source's own compression artefacts exactly.
# Measured on a 12 Mb/s screen capture, it produced a file 7.7x the size of the
# input. CRF 16 is visually indistinguishable at roughly a tenth of that.
#
# The bottom end stops where the picture is still worth looking at rather than
# at the codec's true floor, since no one wants the unusable half of a slider.
_QUALITY_RANGE = {
    "mp4": (36, 16),        # H.264-family QP scale: worst usable, best useful
    "webm": (46, 20),       # VP9 CRF
}

QUALITY_WORDS = (
    (95, "Visually lossless"),
    (80, "Very high"),
    (60, "High"),
    (35, "Good"),
    (0, "Smaller file"),
)


def quality_word(quality: int) -> str:
    """Plain-language name for a slider position."""
    return next(word for floor, word in QUALITY_WORDS if quality >= floor)


def quality_value(preset_name: str, quality: int) -> int | None:
    """The number this codec wants, or None if it has no quality control."""
    if preset_name not in _QUALITY_RANGE:
        return None
    worst, best = _QUALITY_RANGE[preset_name]
    return round(worst + (best - worst) * (max(0, min(100, quality)) / 100))


def quality_args(preset: Preset, quality: int,
                 encoder: encoders.Encoder | None = None) -> list[str]:
    """Map a 0-100 quality slider onto the codec's own scale."""
    value = quality_value(preset.name, quality)
    if value is None:
        return []
    if preset.name == "mp4" and encoder is not None:
        return encoder.args(value)
    return ["-crf", str(value)]


def bitrate_ceiling(doc: EditDoc, quality: int) -> int | None:
    """An upper bound on the output bitrate, sized against the source.

    A quality target alone does not bound the file. Two things exploited that.
    Upscaling asks the encoder to spend bits on pixels carrying no new detail --
    a 3.5x upscale measured 2.4x the size for no more picture. And the hardware
    encoders' quality numbers are not the same scale as libx264's: NVENC at a
    matched setting produced 2.4x the size, because it was given a quality
    target and no ceiling at all.

    So the ceiling is derived from the material: the source's own bitrate,
    scaled by how much of its picture survives. Cropping and downscaling reduce
    it proportionally; upscaling does not raise it, because the extra pixels are
    invented. Quality moves it around parity, where 75 is roughly the source's
    own rate.
    """
    if not doc.source.bitrate:
        return None
    src_px = doc.source.width * doc.source.height
    if src_px <= 0:
        return None
    # Never above 1: more output pixels than the source has cannot mean more
    # detail, so it must not mean more bits.
    ratio = min(1.0, (doc.output.width * doc.output.height) / src_px)
    factor = 0.15 + (max(0, min(100, quality)) / 100) * 1.15
    return max(200_000, int(doc.source.bitrate * ratio * factor))


def ceiling_args(ceiling: int | None) -> list[str]:
    """Cap the bitrate without abandoning quality-targeted encoding.

    The quality setting still decides how many bits the picture deserves; this
    only stops it running away. bufsize is two seconds' worth, which lets a busy
    passage borrow from a quiet one instead of being clipped frame by frame.
    """
    if ceiling is None:
        return []
    return ["-maxrate", str(ceiling), "-bufsize", str(ceiling * 2)]


# --- entry points ----------------------------------------------------------


def atempo_args(speed: float) -> list[str]:
    """Match the audio to a speed change.

    atempo only accepts 0.5 to 2 per instance, so anything beyond that is a
    chain of stages whose product is the requested rate.
    """
    if speed == 1.0:
        return []
    stages: list[float] = []
    remaining = speed
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(remaining)
    return ["-af", ",".join(f"atempo={s:.6g}" for s in stages)]


def _trim_args(doc: EditDoc) -> list[str]:
    """Seek before -i so ffmpeg skips decoding what it is going to discard."""
    args: list[str] = []
    if doc.trim.start > 0:
        args += ["-ss", f"{doc.trim.start:.3f}"]
    if doc.trim.end is not None:
        args += ["-to", f"{doc.trim.end:.3f}"]
    return args


def plan_render(doc: EditDoc, src: Path, dst: Path, workdir: Path,
                preset: str = "mp4", quality: int = 75,
                has_audio: bool = True, accel: str = "auto") -> Plan:
    """A full export.

    `accel` picks the encoder for H.264 output: "auto" takes the fastest one
    this machine can really use, "cpu" forces libx264, or name an encoder.
    Other presets are tied to their codec and ignore it.
    """
    doc.validate()
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; expected one of {sorted(PRESETS)}")
    p = PRESETS[preset]
    encoder = encoders.resolve(accel) if p.name == "mp4" else None

    chain, textfiles = build_chain(doc, workdir)
    if p.max_fps:
        chain = ",".join(filter(None, [chain, f"fps={p.max_fps}"]))
    if p.max_width:
        # -1 keeps the aspect; force even output for codecs that need it.
        chain = ",".join(filter(None, [
            chain, f"scale='min({p.max_width},iw)':-2:flags=lanczos"]))

    if p.name == "gif":
        return _plan_gif(doc, src, dst, chain, textfiles)

    if encoder is not None and encoder.filter_suffix:
        # VAAPI encodes from GPU memory, so frames are uploaded after every
        # filter that works on them.
        chain = ",".join(filter(None, [chain, encoder.filter_suffix]))

    ceiling = bitrate_ceiling(doc, quality) if p.name in ("mp4", "webm") else None

    argv = [
        "ffmpeg", "-y", "-hide_banner", "-nostdin",
        *(encoder.pre_input if encoder else ()),
        *_trim_args(doc), "-i", str(src),
        "-vf", chain,
        *p.video, *quality_args(p, quality, encoder), *ceiling_args(ceiling),
        *(p.audio if has_audio else ["-an"]),
        *(atempo_args(doc.speed) if has_audio else []),
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]
    return Plan(argv=argv, textfiles=textfiles, encoder=encoder.label if encoder else None)


def _plan_gif(doc: EditDoc, src: Path, dst: Path, chain: str,
              textfiles: dict[Path, str]) -> Plan:
    """GIF needs its palette computed from the finished frames, so: two passes.

    A single-pass GIF is limited to a generic 256-colour palette and looks it.
    """
    palette = dst.with_suffix(".palette.png")
    first = [
        "ffmpeg", "-y", "-hide_banner", "-nostdin",
        *_trim_args(doc), "-i", str(src),
        "-vf", f"{chain},palettegen=stats_mode=diff",
        str(palette),
    ]
    second = [
        "ffmpeg", "-y", "-hide_banner", "-nostdin",
        *_trim_args(doc), "-i", str(src), "-i", str(palette),
        "-lavfi", f"{chain}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
        "-progress", "pipe:1", "-nostats",
        str(dst),
    ]
    return Plan(argv=first, textfiles=textfiles, second_pass=second)


def plan_preview(doc: EditDoc, src: Path, dst: Path, workdir: Path,
                 t: float, thumbnail_width: int | None = None) -> Plan:
    """A single frame at `t` seconds into the *source*.

    Written as PNG rather than JPEG. A JPEG of video is re-encoded through
    YCbCr, and a JPEG decoder assumes BT.601 full range whatever the file is
    tagged with, while the source here is BT.709 limited range and the browser
    decodes the video element as such. The preview and the video it replaces
    therefore rendered in visibly different colours -- worst in green, which is
    most of a terrain map -- and every edit flashed between them. RGB has no
    matrix to disagree about.

    Absolute rather than relative to the trim: the editor's scrubber spans the
    whole source and its timecode counts from the file's start, so a preview
    that measured from the in-point would disagree with the position being
    scrubbed. Trimming decides what the export contains, not what can be looked
    at.

    Shares build_chain with plan_render, which is the whole point: this frame is
    proof of what the export will contain, not an approximation of it.
    """
    doc.validate()
    chain, textfiles = build_chain(doc, workdir)
    # Seeking to or past the end returns no frame at all: ffmpeg writes an empty
    # file and fails. Playback stops exactly at the duration, so previewing
    # there has to be clamped back inside the clip.
    #
    # The margin is a frame and a half rather than one. Seek times are formatted
    # to milliseconds and rounding is to nearest, so a clamp of exactly one
    # frame can still be printed as a time later than the final frame's
    # timestamp -- 1.9666667 becomes "1.967" when the last frame is at 1.966667.
    frame = 1.0 / (doc.source.fps or 25)
    last = max(0.0, doc.source.duration - frame * 1.5)
    seek = min(max(0.0, t), last)
    if thumbnail_width:
        chain = ",".join(filter(None, [
            chain, f"scale='min({thumbnail_width},iw)':-2:flags=lanczos"]))

    argv = [
        "ffmpeg", "-y", "-hide_banner", "-nostdin",
        "-ss", f"{seek:.3f}", "-i", str(src),
        "-vf", chain,
        "-frames:v", "1",
        str(dst),
    ]
    return Plan(argv=argv, textfiles=textfiles)
