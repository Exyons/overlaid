"""Project storage.

stdlib sqlite3, no ORM. The schema is two tables and the queries are short
enough to read; an ORM would add a dependency and a layer without removing any
work.

The edit document is stored as a JSON blob rather than shredded into columns.
It is only ever read and written whole, and keeping it opaque means the document
schema can evolve without a migration for every new overlay field.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    src_path    TEXT NOT NULL,
    has_audio   INTEGER NOT NULL,
    doc         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS renders (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at  REAL NOT NULL,
    preset      TEXT NOT NULL,
    status      TEXT NOT NULL,      -- queued | running | done | failed
    progress    REAL NOT NULL DEFAULT 0,
    out_path    TEXT,
    error       TEXT,
    encoder     TEXT,
    size        INTEGER
);

CREATE INDEX IF NOT EXISTS renders_by_project ON renders(project_id, created_at DESC);
"""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    created_at: float
    updated_at: float
    src_path: Path
    has_audio: bool
    doc: dict[str, Any]


@dataclass(frozen=True)
class Render:
    id: str
    project_id: str
    created_at: float
    preset: str
    status: str
    progress: float
    out_path: Path | None
    error: str | None
    encoder: str | None = None
    size: int | None = None


class Db:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA)
            self._migrate(c)

    @staticmethod
    def _migrate(c: sqlite3.Connection) -> None:
        """Add columns that postdate the original schema.

        CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
        so databases made before a column was introduced need it added here.
        """
        have = {r["name"] for r in c.execute("PRAGMA table_info(renders)")}
        for column, decl in (("encoder", "TEXT"), ("size", "INTEGER")):
            if column not in have:
                c.execute(f"ALTER TABLE renders ADD COLUMN {column} {decl}")

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        # check_same_thread=False because renders run on a worker thread; every
        # caller opens its own short-lived connection, so there is no sharing.
        c = sqlite3.connect(self.path, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # --- projects ---------------------------------------------------------

    def create_project(self, name: str, src_path: Path, has_audio: bool,
                       doc: dict[str, Any]) -> Project:
        now = time.time()
        pid = uuid.uuid4().hex[:12]
        with self.conn() as c:
            c.execute(
                "INSERT INTO projects (id, name, created_at, updated_at,"
                " src_path, has_audio, doc) VALUES (?,?,?,?,?,?,?)",
                (pid, name, now, now, str(src_path), int(has_audio),
                 json.dumps(doc)),
            )
        return Project(pid, name, now, now, src_path, has_audio, doc)

    def get_project(self, pid: str) -> Project | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        return _project(row) if row else None

    def list_projects(self) -> list[Project]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [_project(r) for r in rows]

    def update_doc(self, pid: str, doc: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute("UPDATE projects SET doc = ?, updated_at = ? WHERE id = ?",
                      (json.dumps(doc), time.time(), pid))

    def set_src_path(self, pid: str, path: Path) -> None:
        """Point a project at its final upload location once it has one."""
        with self.conn() as c:
            c.execute("UPDATE projects SET src_path = ? WHERE id = ?",
                      (str(path), pid))

    def rename_project(self, pid: str, name: str) -> None:
        with self.conn() as c:
            c.execute("UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                      (name, time.time(), pid))

    def delete_project(self, pid: str) -> list[Path]:
        """Delete the row and return the files that are now orphaned."""
        with self.conn() as c:
            rows = c.execute(
                "SELECT out_path FROM renders WHERE project_id = ? AND out_path"
                " IS NOT NULL", (pid,)).fetchall()
            src = c.execute("SELECT src_path FROM projects WHERE id = ?",
                            (pid,)).fetchone()
            c.execute("DELETE FROM renders WHERE project_id = ?", (pid,))
            c.execute("DELETE FROM projects WHERE id = ?", (pid,))
        files = [Path(r["out_path"]) for r in rows]
        if src:
            files.append(Path(src["src_path"]))
        return files

    # --- renders ----------------------------------------------------------

    def create_render(self, project_id: str, preset: str) -> Render:
        now = time.time()
        rid = uuid.uuid4().hex[:12]
        with self.conn() as c:
            c.execute(
                "INSERT INTO renders (id, project_id, created_at, preset, status,"
                " progress) VALUES (?,?,?,?,'queued',0)",
                (rid, project_id, now, preset),
            )
        return Render(rid, project_id, now, preset, "queued", 0.0, None, None)

    #: Columns update_render may write. The SET clause is built from caller
    #: supplied names, which parameters cannot protect -- only values are bound.
    #: No user input reaches it today, but the check costs nothing and means a
    #: future caller cannot turn a typo into arbitrary SQL.
    RENDER_FIELDS = frozenset(
        {"status", "progress", "out_path", "error", "encoder", "size"})

    def update_render(self, rid: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - self.RENDER_FIELDS
        if unknown:
            raise ValueError(f"cannot update render columns: {sorted(unknown)}")
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.conn() as c:
            c.execute(f"UPDATE renders SET {cols} WHERE id = ?",
                      (*fields.values(), rid))

    def get_render(self, rid: str) -> Render | None:
        with self.conn() as c:
            row = c.execute("SELECT * FROM renders WHERE id = ?", (rid,)).fetchone()
        return _render(row) if row else None

    def list_renders(self, project_id: str) -> list[Render]:
        with self.conn() as c:
            rows = c.execute(
                "SELECT * FROM renders WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,)).fetchall()
        return [_render(r) for r in rows]


def _project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"], name=row["name"],
        created_at=row["created_at"], updated_at=row["updated_at"],
        src_path=Path(row["src_path"]), has_audio=bool(row["has_audio"]),
        doc=json.loads(row["doc"]),
    )


def _render(row: sqlite3.Row) -> Render:
    return Render(
        id=row["id"], project_id=row["project_id"], created_at=row["created_at"],
        preset=row["preset"], status=row["status"], progress=row["progress"],
        out_path=Path(row["out_path"]) if row["out_path"] else None,
        error=row["error"],
        encoder=row["encoder"],
        size=row["size"],
    )
