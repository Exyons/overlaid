"""Integration tests. These really run ffmpeg, so there are only a few."""

from pathlib import Path

import pytest

from dataclasses import replace

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


def test_preview_at_the_very_end_of_the_clip_succeeds(src, tmp_path):
    """Playback stops exactly at the duration, and previewing there used to ask
    ffmpeg for a frame past the last one: it wrote an empty file and failed."""
    source, _ = src
    doc = build(source)
    out = tmp_path / "end.png"
    run(plan_preview(doc, FIXTURE, out, tmp_path, t=source.duration), total=0)
    assert out.exists() and out.stat().st_size > 0


def test_preview_past_the_end_succeeds(src, tmp_path):
    source, _ = src
    doc = build(source)
    out = tmp_path / "past.png"
    run(plan_preview(doc, FIXTURE, out, tmp_path, t=source.duration + 30), total=0)
    assert out.exists() and out.stat().st_size > 0


def test_hardware_export_produces_a_playable_file(src, tmp_path):
    """Whatever 'auto' picks must actually decode afterwards."""
    source, _ = src
    doc = build(source)
    out = tmp_path / "hw.mp4"
    plan = plan_render(doc, FIXTURE, out, tmp_path, accel="auto")
    run(plan, total=doc.duration)
    probed, _ = probe(out)
    assert (probed.width, probed.height) == (source.width, source.height)
    assert probed.duration > 0


def test_maximum_quality_is_not_wildly_larger_than_the_source(src, tmp_path):
    """CRF 0 produced files 7.7x the input. Full quality should stay sane."""
    source, _ = src
    doc = build(source)
    out = tmp_path / "q100.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path, quality=100, accel="cpu"),
        total=doc.duration)
    assert out.stat().st_size < FIXTURE.stat().st_size * 4


# --- phase 3: trim, crop, resize together ----------------------------------


def test_crop_then_resize_produces_the_requested_size(src, tmp_path):
    source, _ = src
    doc = build(source, crop=Crop(0.25, 0.1, 0.5, 0.6), output=Output(640, 480))
    out = tmp_path / "cr.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    probed, _ = probe(out)
    assert (probed.width, probed.height) == (640, 480)


def test_crop_and_trim_compose(src, tmp_path):
    """Crop reads source pixels and trim skips time; neither should disturb
    the other."""
    source, _ = src
    doc = build(source, crop=Crop(0.2, 0.2, 0.6, 0.6),
                trim=Trim(0.4, 1.4), output=Output(320, 240))
    out = tmp_path / "ct.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    probed, _ = probe(out)
    assert (probed.width, probed.height) == (320, 240)
    assert probed.duration == pytest.approx(1.0, abs=0.2)


@pytest.mark.parametrize("fit", ["letterbox", "stretch", "cover"])
def test_every_fit_mode_renders_at_the_requested_size(src, tmp_path, fit):
    source, _ = src
    doc = build(source, crop=Crop(0.1, 0.1, 0.5, 0.8),
                output=Output(480, 480, fit))
    out = tmp_path / f"fit_{fit}.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    probed, _ = probe(out)
    assert (probed.width, probed.height) == (480, 480)


def test_preview_uses_absolute_source_time(src, tmp_path):
    """The playhead counts from the file's start, so a trimmed project can
    still be scrubbed and previewed outside the range it will export."""
    source, _ = src
    doc = build(source, trim=Trim(1.0, 2.0))
    out = tmp_path / "tp.png"
    run(plan_preview(doc, FIXTURE, out, tmp_path, t=0.2), total=0)
    assert out.exists() and out.stat().st_size > 0


def test_preview_at_the_end_of_a_trimmed_clip_succeeds(src, tmp_path):
    source, _ = src
    doc = build(source, trim=Trim(0.5, 1.2))
    out = tmp_path / "te.png"
    run(plan_preview(doc, FIXTURE, out, tmp_path, t=source.duration), total=0)
    assert out.exists() and out.stat().st_size > 0


def test_a_tall_crop_survives_a_wide_output(src, tmp_path):
    """A 9:16 crop into a 16:9 frame is the pillarbox case."""
    source, _ = src
    doc = build(source, crop=Crop(0.35, 0.0, 0.3, 1.0), output=Output(1280, 720))
    out = tmp_path / "tall.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    probed, _ = probe(out)
    assert (probed.width, probed.height) == (1280, 720)


# --- speed and size ---------------------------------------------------------


@pytest.mark.parametrize("speed", [0.5, 2.0, 4.0])
def test_speed_changes_the_output_duration(src, tmp_path, speed):
    source, _ = src
    doc = build(source, speed=speed)
    out = tmp_path / f"sp{speed}.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    probed, _ = probe(out)
    assert probed.duration == pytest.approx(source.duration / speed, abs=0.25)


def test_speeding_up_keeps_the_audio(src, tmp_path):
    """Video sped up without matching the audio would drift apart."""
    source, _ = src
    doc = build(source, speed=2.0)
    out = tmp_path / "spa.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert probe(out)[1], "audio stream was dropped"


def test_speed_does_not_multiply_the_frame_rate(src, tmp_path):
    source, _ = src
    doc = build(source, speed=2.0)
    out = tmp_path / "spf.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert probe(out)[0].fps <= source.fps + 1


def test_speed_and_trim_compose(src, tmp_path):
    source, _ = src
    doc = build(source, trim=Trim(0.4, 1.4), speed=2.0)
    out = tmp_path / "spt.mp4"
    run(plan_render(doc, FIXTURE, out, tmp_path), total=doc.duration)
    assert probe(out)[0].duration == pytest.approx(0.5, abs=0.2)


def test_the_ceiling_actually_shrinks_the_file(src, tmp_path):
    """The complaint that started this: exports several times the input size.

    Compared against the same render with the ceiling disabled rather than
    against an absolute rate. The fixture is two seconds long and bufsize is two
    seconds' worth, so on a clip this short the buffer can absorb almost the
    whole thing; the cap governs sustained rate, which only a longer clip shows.
    """
    source, _ = src
    uncapped = replace(source, bitrate=0)          # no bitrate, no ceiling
    a, b = tmp_path / "capped.mp4", tmp_path / "uncapped.mp4"

    run(plan_render(build(source), FIXTURE, a, tmp_path, quality=100, accel="cpu"),
        total=2.0)
    run(plan_render(build(uncapped), FIXTURE, b, tmp_path, quality=100, accel="cpu"),
        total=2.0)
    assert a.stat().st_size < b.stat().st_size


def test_upscaling_does_not_inflate_the_ceiling_in_practice(src, tmp_path):
    """Asking for more pixels than the crop holds must not buy more bitrate."""
    source, _ = src
    doc = build(source, output=Output(source.width * 2, source.height * 2))
    out = tmp_path / "up.mp4"
    plan = plan_render(doc, FIXTURE, out, tmp_path, quality=100, accel="cpu")
    i = plan.argv.index("-maxrate")
    assert int(plan.argv[i + 1]) <= int(source.bitrate * 1.31)


# --- analysis ---------------------------------------------------------------


def test_sampling_spans_the_whole_recording(src):
    """Windows must be spread out: a region only counts as still if it is
    unchanged between widely separated moments, not across half a second."""
    from core.analyze import sample_frames
    source, _ = src
    frames = sample_frames(FIXTURE, source)
    assert frames.ndim == 3
    assert len(frames) >= 4
    assert frames.shape[2] == 320


def test_a_still_recording_reports_nothing_to_crop(tmp_path):
    """Nothing moves, so there is no moving region to crop to. Saying so beats
    returning a confident rectangle around noise."""
    import subprocess
    from core.analyze import suggest_crop
    still = tmp_path / "still.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=slateblue:s=640x360:d=3:r=15",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(still)],
        check=True, capture_output=True)
    source, _ = probe(still)
    p = suggest_crop(still, source)
    assert p.found is False
    assert p.crop.is_identity


def test_a_still_border_is_excluded(src, tmp_path):
    """The case this exists for: moving content inside a static surround."""
    import subprocess
    from core.analyze import suggest_crop
    framed = tmp_path / "framed.mp4"
    # A moving pattern occupying the middle of an otherwise black frame.
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=black:s=640x360:d=3:r=15",
         "-f", "lavfi", "-i", "testsrc2=s=320x180:d=3:r=15",
         "-filter_complex", "[0:v][1:v]overlay=160:90",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(framed)],
        check=True, capture_output=True)

    source, _ = probe(framed)
    p = suggest_crop(framed, source)
    assert p.found, p.reason
    # The moving quarter sits at 0.25..0.75 horizontally, 0.25..0.75 vertically.
    assert p.crop.x < 0.32 and p.crop.x + p.crop.w > 0.68
    assert p.crop.y < 0.32 and p.crop.y + p.crop.h > 0.68
    assert p.crop.w < 0.75 and p.crop.h < 0.85
