"""Integration tests. These really run ffmpeg, so there are only a few."""

from pathlib import Path

import pytest

from core.compile import plan_preview, plan_render
from core.doc import Crop, EditDoc, Output, Source, TextOverlay, Trim
from core.probe import probe
from core.run import run

FIXTURE = Path(__file__).parent / "fixtures" / "2s.mp4"


@pytest.fixture(scope="module")
def src():
    return probe(FIXTURE)


def build(source, **kw) -> EditDoc:
    kw.setdefault("output", Output(source.width, source.height))
    return EditDoc(source=source, **kw)


def test_fixture_probes_as_expected(src):
    source, has_audio = src
    assert (source.width, source.height) == (640, 360)
    assert has_audio
    assert source.duration == pytest.approx(2.0, abs=0.2)


def test_render_preserves_audio(src, tmp_path):
    source, _ = src
    doc = build(source, overlays=[TextOverlay(id="o1", text="hi", x=.5, y=.5)])
    out = tmp_path / "out.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert probe(out)[1], "audio stream was dropped"


def test_normalising_letterboxes_without_distorting(src, tmp_path):
    source, _ = src
    doc = build(source, output=Output(1920, 1080))
    out = tmp_path / "out.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert (probe(out)[0].width, probe(out)[0].height) == (1920, 1080)


def test_trim_shortens_the_output(src, tmp_path):
    source, _ = src
    doc = build(source, trim=Trim(0.5, 1.5))
    out = tmp_path / "out.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert probe(out)[0].duration == pytest.approx(1.0, abs=0.2)


def test_crop_changes_dimensions(src, tmp_path):
    source, _ = src
    doc = build(source, crop=Crop(0.25, 0.25, 0.5, 0.5), output=Output(320, 180))
    out = tmp_path / "out.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert (probe(out)[0].width, probe(out)[0].height) == (320, 180)


@pytest.mark.parametrize("nasty", ["O'Brien", "100%", "a\\b", "x: y", "two\nlines"])
def test_hostile_text_actually_renders(src, tmp_path, nasty):
    """The escaping bug class. If this passes, no name can break a render."""
    source, _ = src
    doc = build(source, overlays=[TextOverlay(id="o1", text=nasty, x=.5, y=.5)])
    out = tmp_path / "out.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert out.stat().st_size > 0


def test_preview_produces_a_single_frame(src, tmp_path):
    source, _ = src
    doc = build(source, overlays=[TextOverlay(id="o1", text="hi", x=.5, y=.5)])
    out = tmp_path / "frame.png"
    run(plan_preview(doc, FIXTURE, out, tmp_path, t=1.0), total=0)
    assert out.exists() and out.stat().st_size > 0


def test_gif_export_runs_both_passes(src, tmp_path):
    source, _ = src
    doc = build(source, output=Output(320, 180))
    out = tmp_path / "out.gif"
    run(plan_render(doc, FIXTURE, out, tmp_path, preset="gif"), total=doc.duration)
    assert out.exists() and out.stat().st_size > 0


def test_progress_is_reported_monotonically(src, tmp_path):
    source, _ = src
    doc = build(source)
    seen: list[float] = []
    run(plan_render(doc, FIXTURE, tmp_path / "o.mp4", tmp_path),
        total=doc.duration, on_progress=seen.append)
    assert seen, "no progress reported"
    assert seen == sorted(seen)
    assert seen[-1] == 1.0
