"""HTTP surface.

Rendering lives entirely in core/. These handlers validate input, move files
around, and hand documents to the compiler -- deliberately, so the browser can
never produce a video the CLI could not.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import asdict, replace
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core import analyze, encoders, fonts
from core.compile import PRESETS, plan_preview, quality_value, quality_word
from core.doc import DocError, EditDoc, Output
from core.probe import ProbeError, probe
from core.run import RenderError, run

from .db import Db, Project
from .jobs import Jobs

DATA = Path(__file__).resolve().parent.parent / "data"
UPLOADS = DATA / "uploads"
RENDERS = DATA / "renders"
CACHE = DATA / "cache"

#: Browsers will happily let someone pick a 40GB file; refuse it before it
#: lands on disk rather than after.
MAX_UPLOAD = 4 * 1024**3
ALLOWED_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}

db = Db(DATA / "projects.db")
jobs = Jobs(db, RENDERS, CACHE)


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
    return _backfill(p)


def _backfill(p: Project) -> Project:
    """Fill in source facts that a project predates.

    Documents saved before the source bitrate was recorded have no value for it,
    and the export ceiling is derived from that number -- so without this an old
    project would keep exporting uncapped, which is the behaviour that made
    files several times the size of their input. Re-probing is cheap and the
    result is written back, so it happens once per project.
    """
    if p.doc.get("source", {}).get("bitrate"):
        return p
    if not p.src_path.exists():
        return p
    try:
        source, _ = probe(p.src_path)
    except ProbeError:
        return p
    doc = {**p.doc, "source": {**p.doc["source"], "bitrate": source.bitrate}}
    db.update_doc(p.id, doc)
    return replace(p, doc=doc)


@app.exception_handler(DocError)
async def _doc_error(_, exc: DocError) -> JSONResponse:
    """Document problems are the user's to fix, so report them as 400s."""
    return JSONResponse({"detail": str(exc)}, status_code=400)


# --- projects --------------------------------------------------------------


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    return [_json(_backfill(p)) for p in db.list_projects()]


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


#: Library thumbnails do not need full resolution, and a full-size lossless
#: frame per row would be several megabytes each.
THUMBNAIL_WIDTH = 480


def _render_frame(p: Project, doc: EditDoc, t: float, tag: str,
                  thumbnail: bool = False) -> FileResponse:
    out = CACHE / f"{p.id}-{tag}.png"
    plan = plan_preview(doc, p.src_path, out, CACHE / p.id, t=t,
                        thumbnail_width=THUMBNAIL_WIDTH if thumbnail else None)
    try:
        run(plan, total=0)
    except RenderError as e:
        raise HTTPException(500, f"preview failed: {e}") from e
    return FileResponse(out, media_type="image/png",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/projects/{pid}/frame")
def get_frame(pid: str, t: float = Query(0, ge=0)) -> FileResponse:
    """A real rendered frame from the project's saved document, for thumbnails."""
    p = _project_or_404(pid)
    return _render_frame(p, EditDoc.from_dict(p.doc), t, f"{t:.3f}", thumbnail=True)


@app.post("/api/projects/{pid}/frame")
def post_frame(pid: str, t: float = Body(0), doc: dict[str, Any] = Body(...)) -> FileResponse:
    """A real rendered frame from a document the client has not saved yet.

    The editor sends the document it currently holds rather than relying on
    autosave having landed first. That removes an ordering dependency between
    saving and previewing -- and, more importantly, means the frame shown is
    built from exactly the state on screen.
    """
    p = _project_or_404(pid)
    parsed = EditDoc.from_dict(doc).validate()
    return _render_frame(p, parsed, t, "live")


# --- fonts -----------------------------------------------------------------


@app.get("/api/fonts")
def list_fonts() -> list[dict[str, Any]]:
    return [{"id": f.id, "family": f.family, "style": f.style,
             "label": f.label, "path": str(f.path)}
            for f in fonts.available()]


@app.get("/api/fonts/{fid}/file")
def get_font_file(fid: str) -> FileResponse:
    """The font file itself, so the canvas can draw with the face ffmpeg uses."""
    font = fonts.by_id(fid)
    if font is None or not font.path.exists():
        raise HTTPException(404, f"no font {fid}")
    return FileResponse(
        font.path,
        media_type="font/ttf" if font.path.suffix == ".ttf" else "font/otf",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# --- renders ---------------------------------------------------------------


def _render_json(r) -> dict[str, Any]:
    return {"id": r.id, "project_id": r.project_id, "preset": r.preset,
            "status": r.status, "progress": r.progress,
            "error": r.error, "created_at": r.created_at,
            "encoder": r.encoder, "size": r.size,
            "ready": r.status == "done"}


@app.post("/api/projects/{pid}/renders", status_code=202)
def start_render(pid: str, preset: str = Body("mp4", embed=True),
                 quality: int = Body(75, embed=True),
                 accel: str = Body("auto", embed=True)) -> dict[str, Any]:
    """Queue an export. Returns immediately; poll the render for progress."""
    project = _project_or_404(pid)
    if preset not in PRESETS:
        raise HTTPException(400, f"unknown preset {preset!r}")
    EditDoc.from_dict(project.doc).validate()      # fail now, not on the worker
    rid = jobs.submit(pid, preset, quality, accel)
    return _render_json(db.get_render(rid))


@app.post("/api/projects/{pid}/suggest/crop")
def suggest_crop(pid: str) -> dict[str, Any]:
    """Propose a crop around whatever actually moves in the recording.

    A proposal, not an edit: it is returned for the user to accept or adjust,
    and nothing is saved here. Screen captures put a lot of still furniture
    around the part worth keeping, and what moves is a good proxy for that
    without needing to recognise any of it.
    """
    p = _project_or_404(pid)
    doc = EditDoc.from_dict(p.doc)
    try:
        proposal = analyze.suggest_crop(p.src_path, doc.source)
    except analyze.AnalysisError as e:
        raise HTTPException(422, str(e)) from e
    return {
        "crop": asdict(proposal.crop),
        "found": proposal.found,
        "reason": proposal.reason,
        "coverage": proposal.coverage,
    }


@app.get("/api/encoders")
def list_encoders() -> list[dict[str, Any]]:
    """Encoders this machine can really use, fastest first.

    Probed rather than read off `ffmpeg -encoders`, which lists what the binary
    supports rather than what the hardware here will accept.
    """
    return [{"name": e.name, "label": e.label, "kind": e.kind}
            for e in encoders.available()]


@app.get("/api/quality")
def describe_quality(preset: str = Query("mp4"), quality: int = Query(75)) -> dict[str, Any]:
    """What a slider position actually means, so the number is not a mystery."""
    return {"word": quality_word(quality), "value": quality_value(preset, quality)}


@app.get("/api/projects/{pid}/renders")
def list_renders(pid: str) -> list[dict[str, Any]]:
    _project_or_404(pid)
    return [_render_json(r) for r in db.list_renders(pid)]


@app.get("/api/renders/{rid}")
def get_render(rid: str) -> dict[str, Any]:
    r = db.get_render(rid)
    if r is None:
        raise HTTPException(404, f"no render {rid}")
    return _render_json(r)


@app.get("/api/renders/{rid}/file")
def download_render(rid: str) -> FileResponse:
    r = db.get_render(rid)
    if r is None:
        raise HTTPException(404, f"no render {rid}")
    if r.status != "done" or r.out_path is None:
        raise HTTPException(409, f"render is {r.status}")
    if not r.out_path.exists():
        raise HTTPException(410, "the rendered file is gone")
    project = db.get_project(r.project_id)
    name = f"{project.name if project else 'video'}{r.out_path.suffix}"
    return FileResponse(r.out_path, filename=name,
                        media_type="application/octet-stream")


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
