"""HTTP surface.

Rendering lives entirely in core/. These handlers validate input, move files
around, and hand documents to the compiler -- deliberately, so the browser can
never produce a video the CLI could not.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.compile import PRESETS, plan_preview
from core.doc import DocError, EditDoc, Output
from core.probe import ProbeError, probe
from core.run import RenderError, run

from .db import Db, Project

DATA = Path(__file__).resolve().parent.parent / "data"
UPLOADS = DATA / "uploads"
RENDERS = DATA / "renders"
CACHE = DATA / "cache"

#: Browsers will happily let someone pick a 40GB file; refuse it before it
#: lands on disk rather than after.
MAX_UPLOAD = 4 * 1024**3
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

db = Db(DATA / "projects.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (UPLOADS, RENDERS, CACHE):
        d.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="overlaid", lifespan=lifespan)

# The Vite dev server runs on another port; in production the built assets are
# served from this same app and no cross-origin request happens at all.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _json(p: Project) -> dict[str, Any]:
    return {
        "id": p.id, "name": p.name,
        "created_at": p.created_at, "updated_at": p.updated_at,
        "has_audio": p.has_audio, "doc": p.doc,
    }


def _project_or_404(pid: str) -> Project:
    p = db.get_project(pid)
    if p is None:
        raise HTTPException(404, f"no project {pid}")
    return p


@app.exception_handler(DocError)
async def _doc_error(_, exc: DocError) -> JSONResponse:
    """Document problems are the user's to fix, so report them as 400s."""
    return JSONResponse({"detail": str(exc)}, status_code=400)


# --- projects --------------------------------------------------------------


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    return [_json(p) for p in db.list_projects()]


@app.post("/api/projects", status_code=201)
async def create_project(file: UploadFile) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            415, f"unsupported file type {suffix or '(none)'};"
                 f" expected one of {sorted(ALLOWED_SUFFIXES)}")

    UPLOADS.mkdir(parents=True, exist_ok=True)
    # Stream to a temp file first: a file that fails probing should never end up
    # in uploads/ with no project row pointing at it.
    tmp = Path(tempfile.mkstemp(suffix=suffix, dir=UPLOADS)[1])
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "file exceeds 4 GB")
                out.write(chunk)
        try:
            source, has_audio = probe(tmp)
        except ProbeError as e:
            raise HTTPException(400, f"not a readable video: {e}") from e

        doc = EditDoc(source=source, output=Output(source.width, source.height))
        name = Path(file.filename or "untitled").stem
        project = db.create_project(name, tmp, has_audio, doc.to_dict())
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    # Only now that the row exists is there an id to name the file after.
    final = UPLOADS / f"{project.id}{suffix}"
    tmp.rename(final)
    db.set_src_path(project.id, final)
    return _json(_project_or_404(project.id))


@app.get("/api/projects/{pid}")
def get_project(pid: str) -> dict[str, Any]:
    return _json(_project_or_404(pid))


@app.put("/api/projects/{pid}/doc")
def save_doc(pid: str, doc: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _project_or_404(pid)
    parsed = EditDoc.from_dict(doc).validate()      # never store what cannot render
    db.update_doc(pid, parsed.to_dict())
    return _json(_project_or_404(pid))


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, name: str = Body(..., embed=True)) -> dict[str, Any]:
    _project_or_404(pid)
    if not name.strip():
        raise HTTPException(400, "name cannot be empty")
    db.rename_project(pid, name.strip())
    return _json(_project_or_404(pid))


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str) -> None:
    _project_or_404(pid)
    for path in db.delete_project(pid):
        path.unlink(missing_ok=True)


# --- media -----------------------------------------------------------------


@app.get("/api/projects/{pid}/source")
def get_source(pid: str) -> FileResponse:
    """The raw upload, for the <video> element to scrub against."""
    p = _project_or_404(pid)
    if not p.src_path.exists():
        raise HTTPException(410, "source file is missing")
    return FileResponse(p.src_path)


@app.get("/api/projects/{pid}/frame")
def get_frame(pid: str, t: float = Query(0, ge=0)) -> FileResponse:
    """A real rendered frame at `t` seconds into the trimmed clip.

    This is the other half of the hybrid preview: the browser canvas draws an
    approximation while the mouse is down, then asks for this to confirm. It
    shares its filter chain with the export, so what it shows is what ships.
    """
    p = _project_or_404(pid)
    doc = EditDoc.from_dict(p.doc)
    out = CACHE / f"{pid}-{t:.3f}.jpg"

    plan = plan_preview(doc, p.src_path, out, CACHE / pid, t=t)
    try:
        run(plan, total=0)
    except RenderError as e:
        raise HTTPException(500, f"preview failed: {e}") from e
    return FileResponse(out, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/presets")
def get_presets() -> list[dict[str, Any]]:
    return [
        {"name": p.name, "suffix": p.suffix, "warn": p.warn,
         "has_quality": p.name in ("mp4", "webm")}
        for p in PRESETS.values()
    ]


# --- static ----------------------------------------------------------------

# In production the built frontend is served from here, so the whole app is one
# process on one port. In development Vite serves it instead.
DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
