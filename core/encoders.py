"""Pick a video encoder, preferring hardware when it actually works.

`ffmpeg -encoders` lists everything the binary was built with, which is not the
same as what this machine can run: a laptop with a switchable NVIDIA card
advertises h264_nvenc and then fails at CUDA init, and VAAPI will happily bind
to a render node whose driver cannot encode. So each candidate is probed with a
real one-frame encode and only offered if that succeeds.

Hardware encoders are faster but not free: at a matched quality setting they
generally produce a larger file than libx264 for the same picture, because they
spend less effort searching. The choice is exposed rather than hidden.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from functools import lru_cache

PROBE_TIMEOUT = 20


@dataclass(frozen=True)
class Encoder:
    name: str                       # the ffmpeg encoder
    label: str                      # what a person should see
    kind: str                       # "cpu" or "gpu"
    #: Global args that must appear before -i (device selection).
    pre_input: tuple[str, ...] = ()
    #: Filters appended to the chain to move frames where the encoder wants them.
    filter_suffix: str = ""
    #: The option carrying the quality number for this encoder.
    quality_flag: str = "-crf"
    extra: tuple[str, ...] = ()

    def args(self, quality_value: int) -> list[str]:
        return ["-c:v", self.name, self.quality_flag, str(quality_value), *self.extra]


CPU = Encoder(
    name="libx264", label="CPU (libx264)", kind="cpu",
    quality_flag="-crf", extra=("-preset", "medium", "-pix_fmt", "yuv420p"),
)

#: Tried in order; the first that survives its probe wins "auto".
CANDIDATES: tuple[Encoder, ...] = (
    Encoder(
        name="h264_nvenc", label="NVIDIA (NVENC)", kind="gpu",
        quality_flag="-cq",
        extra=("-rc", "vbr", "-preset", "p5", "-b:v", "0", "-pix_fmt", "yuv420p"),
    ),
    Encoder(
        name="h264_qsv", label="Intel Quick Sync", kind="gpu",
        quality_flag="-global_quality",
        extra=("-preset", "medium", "-pix_fmt", "nv12"),
    ),
    Encoder(
        name="h264_vaapi", label="VAAPI", kind="gpu",
        pre_input=("-vaapi_device", "/dev/dri/renderD129"),
        filter_suffix="format=nv12,hwupload",
        quality_flag="-qp", extra=("-rc_mode", "CQP"),
    ),
    Encoder(
        name="h264_vaapi", label="VAAPI", kind="gpu",
        pre_input=("-vaapi_device", "/dev/dri/renderD128"),
        filter_suffix="format=nv12,hwupload",
        quality_flag="-qp", extra=("-rc_mode", "CQP"),
    ),
    CPU,
)


def _works(enc: Encoder) -> bool:
    """Encode one synthetic second and see whether it survives."""
    vf = ["-vf", enc.filter_suffix] if enc.filter_suffix else []
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-nostdin", *enc.pre_input,
        "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30:d=1",
        *vf, *enc.args(24), "-f", "null", "-",
    ]
    try:
        return subprocess.run(cmd, capture_output=True,
                              timeout=PROBE_TIMEOUT).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def available() -> list[Encoder]:
    """Every encoder this machine can really use, best first.

    Probing spawns a handful of short ffmpeg runs, so the result is cached for
    the life of the process.
    """
    found: list[Encoder] = []
    seen: set[str] = set()
    for enc in CANDIDATES:
        if enc.label in seen or not _works(enc):
            continue
        seen.add(enc.label)
        found.append(enc)
    return found or [CPU]


def best() -> Encoder:
    """The fastest encoder that works here."""
    return available()[0]


def resolve(choice: str) -> Encoder:
    """Map a request ("auto", "cpu", or an encoder name) to something usable.

    Falls back to the CPU encoder rather than failing: a machine that loses its
    GPU between renders should still finish the export.
    """
    if choice == "cpu":
        return CPU
    if choice == "auto":
        return best()
    for enc in available():
        if enc.name == choice:
            return enc
    return CPU
