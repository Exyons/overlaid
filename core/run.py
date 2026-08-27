"""Execute a compiled Plan, reporting progress as it goes."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from .compile import Plan


class RenderError(RuntimeError):
    """ffmpeg exited non-zero. The message carries its last words."""


ProgressFn = Callable[[float], None]


def run(plan: Plan, total: float, on_progress: ProgressFn | None = None) -> None:
    """Materialise the plan's sidecar files and execute it.

    `total` is the expected output duration in seconds, used to turn ffmpeg's
    `out_time_us` reports into a 0..1 fraction. A two-pass plan (GIF) reports
    the first pass as the leading half of the bar.
    """
    plan.materialise()
    passes = [plan.argv] + ([plan.second_pass] if plan.second_pass else [])
    span = 1.0 / len(passes)

    for i, argv in enumerate(passes):
        def scaled(f: float, i=i) -> None:
            if on_progress:
                on_progress(min(1.0, (i + f) * span))
        _exec(argv, total, scaled)
    if on_progress:
        on_progress(1.0)


def _exec(argv: list[str], total: float, on_progress: ProgressFn) -> None:
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        # -progress emits key=value lines; out_time_us is the one worth reading.
        if line.startswith("out_time_us=") and total > 0:
            raw = line.split("=", 1)[1].strip()
            if raw.isdigit():
                on_progress(min(1.0, int(raw) / 1e6 / total))
    proc.wait()
    if proc.returncode != 0:
        stderr = (proc.stderr.read() if proc.stderr else "").strip()
        tail = "\n".join(stderr.splitlines()[-4:])
        raise RenderError(tail or f"ffmpeg exited {proc.returncode}")


def workdir() -> Path:
    """A scratch directory for a render's sidecar text files."""
    return Path(tempfile.mkdtemp(prefix="videdit-"))
