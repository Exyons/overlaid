"""Background renders.

A render takes seconds to minutes, so the request that starts one returns a job
id immediately and the client watches progress separately. A single worker
thread processes the queue: ffmpeg already saturates the CPU, so running several
at once would finish none of them sooner.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from core.compile import PRESETS, plan_render
from core.doc import EditDoc
from core.run import RenderError, run

from .db import Db


class Jobs:
    def __init__(self, db: Db, renders: Path, workdir: Path) -> None:
        self.db = db
        self.renders = renders
        self.workdir = workdir
        self._q: queue.Queue[str] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, project_id: str, preset: str, quality: int) -> str:
        """Queue a render and return its id."""
        render = self.db.create_render(project_id, preset)
        self._q.put(f"{render.id}\t{quality}")
        self._ensure_worker()
        return render.id

    def _ensure_worker(self) -> None:
        # Started lazily so importing the app does not spawn a thread, which
        # keeps the test suite free of background work it did not ask for.
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()

    def _loop(self) -> None:
        while True:
            try:
                item = self._q.get(timeout=30)
            except queue.Empty:
                return                      # idle: let the thread go
            rid, _, quality = item.partition("\t")
            try:
                self._render(rid, int(quality))
            except Exception as e:          # a crash must not kill the worker
                self.db.update_render(rid, status="failed", error=str(e))
            finally:
                self._q.task_done()

    def _render(self, rid: str, quality: int) -> None:
        render = self.db.get_render(rid)
        if render is None:
            return
        project = self.db.get_project(render.project_id)
        if project is None:
            self.db.update_render(rid, status="failed", error="project was deleted")
            return

        self.db.update_render(rid, status="running", progress=0.0)
        doc = EditDoc.from_dict(project.doc)
        suffix = PRESETS[render.preset].suffix
        out = self.renders / f"{rid}{suffix}"

        # Progress is written straight to the row: the status endpoint polls it,
        # so there is no in-memory state to lose if the process restarts.
        last = 0.0
        def report(f: float) -> None:
            nonlocal last
            if f - last >= 0.01 or f >= 1.0:
                last = f
                self.db.update_render(rid, progress=f)

        try:
            plan = plan_render(doc, project.src_path, out, self.workdir / rid,
                               preset=render.preset, quality=quality,
                               has_audio=project.has_audio)
            run(plan, total=doc.duration, on_progress=report)
        except (RenderError, ValueError) as e:
            self.db.update_render(rid, status="failed", error=str(e))
            return
        self.db.update_render(rid, status="done", progress=1.0, out_path=str(out))
