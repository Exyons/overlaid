"""API tests. These drive the real app against a temp data directory."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / "fixtures" / "2s.mp4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh app whose data directory is thrown away after each test.

    The job queue holds its own reference to the database, so it has to be
    rebuilt alongside it -- patching only `db` leaves the worker writing to the
    real one.
    """
    import api.main as m
    from api.db import Db
    from api.jobs import Jobs

    db = Db(tmp_path / "t.db")
    for name, value in [
        ("UPLOADS", tmp_path / "uploads"),
        ("RENDERS", tmp_path / "renders"),
        ("CACHE", tmp_path / "cache"),
        ("db", db),
        ("jobs", Jobs(db, tmp_path / "renders", tmp_path / "cache")),
    ]:
        monkeypatch.setattr(m, name, value)
    with TestClient(m.app) as c:
        yield c


def upload(client, name="clip.mp4"):
    with FIXTURE.open("rb") as f:
        return client.post("/api/projects", files={"file": (name, f, "video/mp4")})


def test_upload_creates_a_project_with_probed_dimensions(client):
    r = upload(client)
    assert r.status_code == 201
    body = r.json()
    assert body["doc"]["source"]["width"] == 640
    assert body["doc"]["output"]["width"] == 640      # defaults to pass-through
    assert body["has_audio"] is True
    assert body["name"] == "clip"


def test_upload_rejects_non_video_extensions(client):
    r = client.post("/api/projects",
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_upload_rejects_a_file_that_is_not_really_video(client):
    r = client.post("/api/projects",
                    files={"file": ("fake.mp4", b"not a video", "video/mp4")})
    assert r.status_code == 400


def test_a_rejected_upload_leaves_no_file_behind(client, tmp_path):
    client.post("/api/projects",
                files={"file": ("fake.mp4", b"not a video", "video/mp4")})
    uploads = tmp_path / "uploads"
    assert not uploads.exists() or list(uploads.iterdir()) == []


def test_project_round_trips(client):
    pid = upload(client).json()["id"]
    assert client.get(f"/api/projects/{pid}").json()["id"] == pid
    assert len(client.get("/api/projects").json()) == 1


def test_missing_project_is_404(client):
    assert client.get("/api/projects/nope").status_code == 404


def test_saving_a_document_persists_it(client):
    p = upload(client).json()
    doc = p["doc"]
    doc["overlays"] = [{
        "id": "o1", "type": "text", "text": "hello", "x": 0.5, "y": 0.5,
        "anchor": "bottom-right", "size": 0.03,
        "font": "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "color": "#ffffff", "box": None, "line_gap": 0.35,
        "start": None, "end": None,
    }]
    r = client.put(f"/api/projects/{p['id']}/doc", json=doc)
    assert r.status_code == 200
    stored = client.get(f"/api/projects/{p['id']}").json()["doc"]
    assert stored["overlays"][0]["text"] == "hello"


def test_an_unrenderable_document_is_rejected(client):
    p = upload(client).json()
    doc = p["doc"]
    doc["output"]["width"] = 641           # odd, yuv420p cannot encode it
    r = client.put(f"/api/projects/{p['id']}/doc", json=doc)
    assert r.status_code == 400
    assert "even" in r.json()["detail"]


def test_bad_crop_is_rejected(client):
    p = upload(client).json()
    doc = p["doc"]
    doc["crop"] = {"x": 0.8, "y": 0.0, "w": 0.5, "h": 1.0}   # runs off the edge
    assert client.put(f"/api/projects/{p['id']}/doc", json=doc).status_code == 400


def test_frame_endpoint_returns_a_jpeg(client):
    pid = upload(client).json()["id"]
    r = client.get(f"/api/projects/{pid}/frame", params={"t": 1.0})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"           # JPEG magic


def test_source_is_served_with_range_support(client):
    """The <video> element needs ranges to scrub without downloading it all."""
    pid = upload(client).json()["id"]
    r = client.get(f"/api/projects/{pid}/source", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206
    assert len(r.content) == 100


def test_rename(client):
    pid = upload(client).json()["id"]
    r = client.patch(f"/api/projects/{pid}", json={"name": "  demo  "})
    assert r.json()["name"] == "demo"


def test_delete_removes_the_row_and_the_file(client):
    p = upload(client).json()
    assert client.delete(f"/api/projects/{p['id']}").status_code == 204
    assert client.get(f"/api/projects/{p['id']}").status_code == 404
    assert client.get("/api/projects").json() == []


def test_presets_are_listed(client):
    names = {p["name"] for p in client.get("/api/presets").json()}
    assert names == {"mp4", "webm", "gif", "mov"}


# --- fonts -----------------------------------------------------------------


def test_fonts_are_listed_with_ids(client):
    fonts = client.get("/api/fonts").json()
    assert fonts, "no fonts discovered"
    assert {"id", "family", "style", "label", "path"} <= set(fonts[0])


def test_a_font_file_can_be_fetched_by_id(client):
    """The canvas needs the real face, or its text metrics are a guess."""
    fid = client.get("/api/fonts").json()[0]["id"]
    r = client.get(f"/api/fonts/{fid}/file")
    assert r.status_code == 200
    assert r.content[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true")   # sfnt magic


def test_unknown_font_is_404(client):
    assert client.get("/api/fonts/deadbeef/file").status_code == 404


# --- renders ---------------------------------------------------------------


def wait_for(client, rid, timeout=60):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/renders/{rid}").json()
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(0.15)
    raise AssertionError("render did not finish")


def test_render_runs_and_produces_a_downloadable_file(client):
    pid = upload(client).json()["id"]
    rid = client.post(f"/api/projects/{pid}/renders",
                      json={"preset": "mp4", "quality": 40}).json()["id"]
    result = wait_for(client, rid)
    assert result["status"] == "done", result["error"]

    dl = client.get(f"/api/renders/{rid}/file")
    assert dl.status_code == 200
    assert len(dl.content) > 0
    assert "clip.mp4" in dl.headers.get("content-disposition", "")


def test_downloading_an_unfinished_render_is_409(client):
    pid = upload(client).json()["id"]
    rid = client.post(f"/api/projects/{pid}/renders", json={"preset": "mp4"}).json()["id"]
    r = client.get(f"/api/renders/{rid}/file")
    assert r.status_code in (409, 200)      # 200 only if it already finished


def test_unknown_preset_is_rejected_before_queueing(client):
    pid = upload(client).json()["id"]
    r = client.post(f"/api/projects/{pid}/renders", json={"preset": "avi"})
    assert r.status_code == 400


def test_renders_are_listed_per_project(client):
    pid = upload(client).json()["id"]
    client.post(f"/api/projects/{pid}/renders", json={"preset": "mp4"})
    assert len(client.get(f"/api/projects/{pid}/renders").json()) == 1


# --- live preview ----------------------------------------------------------


def overlay_doc(doc, **over):
    doc = {**doc}
    doc["overlays"] = [{
        "id": "o1", "type": "text", "text": "hello", "x": 0.5, "y": 0.5,
        "anchor": "middle-center", "size": 0.05,
        "font": "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "color": "#ffffff", "box": None, "line_gap": 0.35,
        "start": None, "end": None, **over,
    }]
    return doc


def test_live_frame_uses_the_posted_document_not_the_saved_one(client):
    """The editor previews unsaved state, so autosave cannot race the preview."""
    p = upload(client).json()
    saved = client.get(f"/api/projects/{p['id']}").json()["doc"]
    assert saved["overlays"] == []

    r = client.post(f"/api/projects/{p['id']}/frame",
                    json={"t": 0.5, "doc": overlay_doc(p["doc"])})
    assert r.status_code == 200
    assert r.content[:2] == b"\xff\xd8"
    # The document was never saved: previewing must not persist it.
    assert client.get(f"/api/projects/{p['id']}").json()["doc"]["overlays"] == []


def test_live_frame_rejects_an_invalid_document(client):
    p = upload(client).json()
    doc = overlay_doc(p["doc"], anchor="middle")        # not a real anchor
    r = client.post(f"/api/projects/{p['id']}/frame", json={"t": 0, "doc": doc})
    assert r.status_code == 400


def test_live_frame_renders_hostile_text(client):
    """The escaping path, exercised through the API the editor actually uses."""
    p = upload(client).json()
    doc = overlay_doc(p["doc"], text="O'Brien: 100%\nCS & E")
    r = client.post(f"/api/projects/{p['id']}/frame", json={"t": 0, "doc": doc})
    assert r.status_code == 200, r.text


# --- analysis ---------------------------------------------------------------


def test_crop_suggestion_returns_a_proposal(client):
    p = upload(client).json()
    r = client.post(f"/api/projects/{p['id']}/suggest/crop")
    assert r.status_code == 200
    body = r.json()
    assert {"crop", "found", "reason", "coverage"} <= set(body)
    assert {"x", "y", "w", "h"} == set(body["crop"])


def test_a_suggestion_never_saves_anything(client):
    """A proposal the user has not accepted must not become the document."""
    p = upload(client).json()
    before = client.get(f"/api/projects/{p['id']}").json()["doc"]["crop"]
    client.post(f"/api/projects/{p['id']}/suggest/crop")
    after = client.get(f"/api/projects/{p['id']}").json()["doc"]["crop"]
    assert before == after


def test_a_suggested_crop_is_always_renderable(client):
    """Whatever comes back has to survive validation, or accepting it breaks."""
    p = upload(client).json()
    body = client.post(f"/api/projects/{p['id']}/suggest/crop").json()
    doc = {**p["doc"], "crop": body["crop"]}
    assert client.put(f"/api/projects/{p['id']}/doc", json=doc).status_code == 200
