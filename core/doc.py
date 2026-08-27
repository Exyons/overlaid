"""The edit document: the single source of truth for what a render should produce.

Every geometric value here is normalized to 0..1 rather than stored in pixels.
Crop is a fraction of the source frame; overlay position and font size are
fractions of the *output* frame. That distinction is deliberate — text is drawn
after scaling and padding, so it must be positionable anywhere on the final
canvas, including the letterbox bars. It also means changing the export
resolution rescales the whole layout instead of breaking it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

DEFAULT_FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"

# An anchor names which point of the text block sits at (x, y). Right-anchored
# text grows leftward, so a longer string can never run off the frame edge.
H_ANCHORS = ("left", "center", "right")
V_ANCHORS = ("top", "middle", "bottom")
ANCHORS = tuple(f"{v}-{h}" for v in V_ANCHORS for h in H_ANCHORS)

FITS = ("letterbox", "stretch", "cover")


class DocError(ValueError):
    """The document is not renderable. Message is safe to show a user."""


@dataclass(frozen=True)
class Source:
    width: int
    height: int
    fps: float
    duration: float


@dataclass(frozen=True)
class Trim:
    start: float = 0.0
    end: float | None = None      # None means "to the end of the source"

    def validate(self, duration: float) -> None:
        if self.start < 0:
            raise DocError("trim.start cannot be negative")
        if self.end is not None:
            if self.end <= self.start:
                raise DocError("trim.end must be greater than trim.start")
            if self.start >= duration:
                raise DocError("trim.start is past the end of the video")


@dataclass(frozen=True)
class Crop:
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0

    @property
    def is_identity(self) -> bool:
        return (self.x, self.y, self.w, self.h) == (0.0, 0.0, 1.0, 1.0)

    def validate(self) -> None:
        if not (0 < self.w <= 1) or not (0 < self.h <= 1):
            raise DocError("crop width and height must be within (0, 1]")
        if self.x < 0 or self.y < 0:
            raise DocError("crop origin cannot be negative")
        if self.x + self.w > 1 + 1e-9 or self.y + self.h > 1 + 1e-9:
            raise DocError("crop rectangle extends past the source frame")


@dataclass(frozen=True)
class Output:
    width: int
    height: int
    fit: str = "letterbox"

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise DocError("output dimensions must be positive")
        if self.width % 2 or self.height % 2:
            raise DocError("output dimensions must be even (yuv420p requirement)")
        if self.fit not in FITS:
            raise DocError(f"unknown fit {self.fit!r}; expected one of {FITS}")


@dataclass(frozen=True)
class Box:
    """The plate drawn behind text so it stays legible over busy footage."""
    color: str = "#000000"
    alpha: float = 0.55
    pad: float = 0.5              # as a fraction of font size


@dataclass(frozen=True)
class TextOverlay:
    id: str
    text: str
    x: float
    y: float
    anchor: str = "bottom-right"
    size: float = 0.030           # cap height as a fraction of output height
    font: str = DEFAULT_FONT
    color: str = "#ffffff"
    box: Box | None = field(default_factory=Box)
    line_gap: float = 0.35        # leading, as a fraction of font size
    start: float | None = None    # None means "for the whole clip"
    end: float | None = None
    type: str = "text"

    def validate(self) -> None:
        if not self.id:
            raise DocError("overlay needs an id")
        if self.anchor not in ANCHORS:
            raise DocError(f"unknown anchor {self.anchor!r}; expected one of {ANCHORS}")
        if self.size <= 0:
            raise DocError("overlay size must be positive")
        if not Path(self.font).exists():
            raise DocError(f"font not found: {self.font}")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise DocError(f"overlay {self.id}: end must be greater than start")

    @property
    def is_timed(self) -> bool:
        return self.start is not None or self.end is not None


@dataclass
class EditDoc:
    source: Source
    output: Output
    trim: Trim = field(default_factory=Trim)
    crop: Crop = field(default_factory=Crop)
    overlays: list[TextOverlay] = field(default_factory=list)
    version: int = 1

    def validate(self) -> EditDoc:
        """Raise DocError on anything the compiler could not render. Returns self."""
        self.output.validate()
        self.crop.validate()
        self.trim.validate(self.source.duration)
        seen: set[str] = set()
        for o in self.overlays:
            o.validate()
            if o.id in seen:
                raise DocError(f"duplicate overlay id {o.id!r}")
            seen.add(o.id)
        return self

    @property
    def duration(self) -> float:
        """Output duration in seconds, after trimming."""
        end = self.trim.end if self.trim.end is not None else self.source.duration
        return max(0.0, min(end, self.source.duration) - self.trim.start)

    # --- serialisation ----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), **kw)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EditDoc:
        version = d.get("version", 1)
        if version != 1:
            raise DocError(f"unsupported document version {version}")
        overlays = []
        for o in d.get("overlays", []):
            o = dict(o)
            box = o.pop("box", None)
            overlays.append(TextOverlay(box=Box(**box) if box else None, **o))
        return cls(
            source=Source(**d["source"]),
            output=Output(**d["output"]),
            trim=Trim(**d.get("trim", {})),
            crop=Crop(**d.get("crop", {})),
            overlays=overlays,
            version=version,
        )

    @classmethod
    def from_json(cls, s: str) -> EditDoc:
        return cls.from_dict(json.loads(s))

    @classmethod
    def for_source(cls, src: Source, **kw: Any) -> EditDoc:
        """A pass-through document: same resolution in as out, no edits."""
        return cls(source=src, output=Output(src.width, src.height), **kw)
