"""Execute a compiled Plan, reporting progress as it goes."""

from __future__ import annotations

import subprocess
import tempfile
import threading
from collections import deque
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


#: Lines of ffmpeg's stderr kept for the error message. The rest is discarded as
#: it arrives, so a run that logs megabytes costs nothing to hold.
ERROR_LINES = 8


def _exec(argv: list[str], total: float, on_progress: ProgressFn) -> None:
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None and proc.stderr is not None

    # stderr is drained on its own thread rather than read after the process
    # exits. A pipe holds about 64KB; once ffmpeg fills it, it blocks trying to
    # write more and stops producing stdout, while this side blocks reading
    # stdout that can never arrive. Neither ever proceeds. A failing render logs
    # far more than 64KB, and because renders run on a single worker, one such
    # job would stop every export until the process was restarted.
    tail: deque[str] = deque(maxlen=ERROR_LINES)

    def drain() -> None:
        for line in proc.stderr:            # type: ignore[union-attr]
            stripped = line.rstrip()
            if stripped:
                tail.append(stripped)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()

    try:
        for line in proc.stdout:
            # -progress emits key=value lines; out_time_us is the one worth reading.
            if line.startswith("out_time_us=") and total > 0:
                raw = line.split("=", 1)[1].strip()
                if raw.isdigit():
                    on_progress(min(1.0, int(raw) / 1e6 / total))
        proc.wait()
    finally:
        reader.join(timeout=5)
        proc.stdout.close()
        proc.stderr.close()

    if proc.returncode != 0:
        raise RenderError("\n".join(tail) or f"ffmpeg exited {proc.returncode}")


def workdir() -> Path:
    """A scratch directory for a render's sidecar text files."""
    return Path(tempfile.mkdtemp(prefix="videdit-"))
