"""Discover the fonts the renderer can actually use.

The edit document stores an absolute font path, because the renderer needs one
and this is a local tool. The browser cannot read that path, so each font also
gets a stable id the API can serve the file under -- the canvas has to draw with
the same face ffmpeg will, or the preview would misplace text it cannot measure.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Variable and colour fonts, and formats FreeType handles inconsistently, are
#: filtered out: drawtext and the browser disagree about them often enough that
#: offering them would undermine the preview's whole promise.
USABLE_SUFFIXES = {".ttf", ".otf"}


@dataclass(frozen=True)
class Font:
    id: str
    family: str
    style: str
    path: Path

    @property
    def label(self) -> str:
        return f"{self.family} {self.style}".strip()


def _id_for(path: Path) -> str:
    """A stable, filesystem-independent handle for a font file."""
    return hashlib.sha1(str(path).encode()).hexdigest()[:12]


@lru_cache(maxsize=1)
def available() -> list[Font]:
    """Every usable font on the system, sorted by family then style."""
    try:
        out = subprocess.run(
            ["fc-list", "--format", "%{file}\\t%{family[0]}\\t%{style[0]}\\n"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return _fallback()

    fonts: dict[str, Font] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        raw, family, style = (p.strip() for p in parts)
        path = Path(raw)
        if path.suffix.lower() not in USABLE_SUFFIXES or not family:
            continue
        fid = _id_for(path)
        fonts.setdefault(fid, Font(fid, family, style or "Regular", path))

    if not fonts:
        return _fallback()
    return sorted(fonts.values(), key=lambda f: (f.family.lower(), f.style.lower()))


def _fallback() -> list[Font]:
    """When fontconfig is unavailable, offer whatever the default font is."""
    from .doc import DEFAULT_FONT
    path = Path(DEFAULT_FONT)
    if not path.exists():
        return []
    return [Font(_id_for(path), "DejaVu Sans", "Bold", path)]


def by_id(fid: str) -> Font | None:
    return next((f for f in available() if f.id == fid), None)


def by_path(path: str | Path) -> Font | None:
    target = Path(path)
    return next((f for f in available() if f.path == target), None)
