"""Read what ffmpeg thinks is in a media file."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .doc import Source


#: A local file should answer in well under this. The limit exists so a damaged
#: or stalled file reports a failure instead of hanging the caller forever.
PROBE_TIMEOUT = 30


class ProbeError(RuntimeError):
    """The file could not be read as video."""


def probe(path: Path) -> tuple[Source, bool]:
    """Return the video's parameters and whether it carries an audio stream."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise ProbeError(f"ffprobe gave up on {path.name} "
                         f"after {PROBE_TIMEOUT}s") from e
    if out.returncode != 0:
        raise ProbeError(out.stderr.strip() or f"ffprobe failed on {path}")

    data = json.loads(out.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ProbeError(f"no video stream in {path.name}")

    # Container duration is more reliable than the stream's for trimmed files.
    duration = float(data.get("format", {}).get("duration")
                     or video.get("duration") or 0.0)

    # The video stream usually carries its own bitrate; when it does not, fall
    # back to the container's, which includes audio and so reads a little high.
    bitrate = int(float(video.get("bit_rate")
                        or data.get("format", {}).get("bit_rate") or 0))

    return Source(
        width=int(video["width"]),
        height=int(video["height"]),
        fps=_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        duration=duration,
        bitrate=bitrate,
    ), any(s.get("codec_type") == "audio" for s in streams)


def _fps(rate: str | None) -> float:
    """ffprobe reports frame rate as a rational string like '60/1'."""
    if not rate or "/" not in rate:
        return float(rate) if rate else 0.0
    num, den = rate.split("/")
    return float(num) / float(den) if float(den) else 0.0
