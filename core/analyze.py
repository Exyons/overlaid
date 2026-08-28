"""Look at the footage and propose edits.

This is where OpenCV earns its place. Everything up to here describes what to
render; this reads what was recorded and suggests what the description should
say. Nothing here applies an edit -- each function returns a proposal for the
user to accept, adjust or ignore, because an analysis that is confidently wrong
is worse than no analysis at all.

Frames are sampled through ffmpeg rather than cv2.VideoCapture, which seeks a
long recording slowly and imprecisely, and from short windows spread across the
timeline rather than the whole of it -- decoding every frame to keep a few dozen
is most of the cost, and skipping between windows removes it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .doc import Crop, Source

#: Short stretches to look at, spread over the recording. Sampling windows
#: rather than the whole timeline is what keeps this quick: an `fps` filter
#: decodes every frame in the file to keep a handful, which measured 8.4s on a
#: three-minute capture against 1.7s for the same number of frames taken from
#: eight half-second windows.
WINDOWS = 8
WINDOW_SECONDS = 0.5
WINDOW_FPS = 8

#: Width the samples are decoded at. The regions being found are large, so the
#: detail lost here costs nothing and the analysis stays quick.
SAMPLE_WIDTH = 320


class AnalysisError(RuntimeError):
    """The footage could not be analysed. Message is safe to show a user."""


@dataclass(frozen=True)
class CropProposal:
    crop: Crop
    #: Share of the frame the proposal keeps, for reporting.
    coverage: float
    #: False when nothing stood out and the whole frame is being returned.
    found: bool
    reason: str


def sample_frames(src: Path, source: Source, windows: int = WINDOWS,
                  width: int = SAMPLE_WIDTH) -> np.ndarray:
    """Decode greyscale frames from windows spread across the recording.

    Returns an (n, h, w) array. The windows are what matter: a region only
    counts as still if it is unchanged between widely separated moments, and
    seeking to each window costs nothing compared with decoding the file
    through.
    """
    if source.duration <= 0:
        raise AnalysisError("the video has no duration to sample")

    height = max(2, round(width * source.height / source.width) // 2 * 2)
    frame_bytes = width * height
    span = min(WINDOW_SECONDS, max(source.duration / windows, 0.1))
    chunks: list[bytes] = []
    errors: list[str] = []

    for i in range(windows):
        at = source.duration * (i + 0.5) / windows
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin",
             "-ss", f"{at:.3f}", "-t", f"{span:.3f}", "-i", str(src),
             "-vf", f"fps={WINDOW_FPS},scale={width}:{height}",
             "-pix_fmt", "gray", "-f", "rawvideo", "-"],
            capture_output=True,
        )
        if out.returncode != 0:
            errors.append(out.stderr.decode(errors="replace").strip()[:120])
            continue
        for j in range(len(out.stdout) // frame_bytes):
            chunks.append(out.stdout[j * frame_bytes:(j + 1) * frame_bytes])

    if len(chunks) < 2:
        raise AnalysisError(errors[0] if errors else "not enough frames to compare")
    return (np.frombuffer(b"".join(chunks), dtype=np.uint8)
            .reshape(len(chunks), height, width))


def suggest_crop(src: Path, source: Source) -> CropProposal:
    """Propose a crop around the part of the picture that actually changes.

    A screen recording holds a lot that never moves -- browser chrome, tabs, a
    settings panel -- around a region that does. Measuring how much each pixel
    varies over time separates the two without needing to know what any of it
    is: the still furniture scores near zero, the content does not.
    """
    import cv2

    frames = sample_frames(src, source).astype(np.float32)
    # Standard deviation over time: high where the picture changes, ~0 where it
    # is the same furniture in every frame.
    motion = frames.std(axis=0)
    if motion.max() < 1.0:
        return CropProposal(Crop(), 1.0, False,
                            "Nothing in this recording moves enough to find an edge.")

    norm = cv2.normalize(motion, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    # Otsu picks the split between moving and still for this recording rather
    # than against a fixed threshold that would suit only one kind of capture.
    _, mask = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Close small gaps so a region broken up by momentarily static patches --
    # a paused animation, a flat area of colour -- still reads as one shape.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return CropProposal(Crop(), 1.0, False,
                            "Could not separate the moving part of the picture.")

    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    fh, fw = mask.shape
    crop = Crop(x=x / fw, y=y / fh, w=w / fw, h=h / fh)
    coverage = crop.w * crop.h

    # A proposal covering nearly everything is not a finding, and one covering
    # almost nothing is a glitch rather than a region. Say so instead of
    # returning a crop that would have to be undone.
    if coverage > 0.92:
        return CropProposal(Crop(), 1.0, False,
                            "The whole frame is in motion, so there is nothing to trim.")
    if coverage < 0.02:
        return CropProposal(Crop(), 1.0, False,
                            "Only a few scattered pixels move; no region to crop to.")

    return CropProposal(
        crop=_pad(crop, fw, fh),
        coverage=coverage,
        found=True,
        reason=f"Found a moving region covering {coverage:.0%} of the frame.",
    )


def _pad(crop: Crop, width: int, height: int, pixels: int = 3) -> Crop:
    """Widen a proposal slightly.

    The threshold sits just inside the true edge, since the outermost row of a
    moving region varies less than its middle. A few sample pixels of margin
    stops the proposal shaving the content it found.
    """
    dx, dy = pixels / width, pixels / height
    x = max(0.0, crop.x - dx)
    y = max(0.0, crop.y - dy)
    return Crop(
        x=x, y=y,
        w=min(1.0 - x, crop.w + dx * 2),
        h=min(1.0 - y, crop.h + dy * 2),
    )
