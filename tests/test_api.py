"""API tests. These drive the real app against a temp data directory."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURE = Path(__file__).parent / "fixtures" / "2s.mp4"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh app whose data directory is thrown away after each test."""
    import api.main as m
    from api.db import Db

    monkeypatch.setattr(m, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(m, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(m, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(m, "db", Db(tmp_path / "t.db"))
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
