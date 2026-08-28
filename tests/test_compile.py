"""Compiler tests. These do not run ffmpeg -- see test_render.py for that."""

from pathlib import Path

import pytest

from core.compile import (
    PRESETS, anchor_expr, build_chain, fit_inside, plan_preview, plan_render,
    quality_args, quality_value, quality_word,
)
from core.encoders import CPU
from core.doc import Crop, DocError, EditDoc, Output, Source, TextOverlay, Trim

WORK = Path("/tmp/work")
SRC = Source(1856, 1116, 60.0, 70.65)


def doc(**kw) -> EditDoc:
    kw.setdefault("source", SRC)
    kw.setdefault("output", Output(1920, 1080))
    return EditDoc(**kw)


def overlay(**kw) -> TextOverlay:
    kw.setdefault("id", "o1")
    kw.setdefault("text", "hello")
    kw.setdefault("x", 0.5)
    kw.setdefault("y", 0.5)
    return TextOverlay(**kw)


# --- ordering -------------------------------------------------------------


def test_filters_are_ordered_crop_scale_pad_text():
    """Text must land after padding, or it cannot be placed in the bars."""
    chain, _ = build_chain(
        doc(crop=Crop(0.1, 0.1, 0.8, 0.8), overlays=[overlay()]), WORK)
    names = [f.split("=")[0] for f in chain.split(",") if "=" in f]
    assert names.index("crop") < names.index("scale")
    assert names.index("scale") < names.index("pad")
    assert names.index("pad") < names.index("drawtext")


def test_identity_crop_emits_no_crop_filter():
    chain, _ = build_chain(doc(), WORK)
    assert "crop=" not in chain


def test_matching_aspect_needs_no_pad():
    same = doc(source=Source(1920, 1080, 30, 10), output=Output(1280, 720))
    chain, _ = build_chain(same, WORK)
    assert "pad=" not in chain
    assert "scale=1280:720" in chain


# --- anchors --------------------------------------------------------------


@pytest.mark.parametrize("anchor,ex,ey", [
    ("top-left",      "w*0.5",        "h*0.5"),
    ("top-right",     "w*0.5-tw",     "h*0.5"),
    ("bottom-left",   "w*0.5",        "h*0.5-th"),
    ("bottom-right",  "w*0.5-tw",     "h*0.5-th"),
    ("middle-center", "w*0.5-tw/2",   "h*0.5-th/2"),
])
def test_anchor_expressions(anchor, ex, ey):
    assert anchor_expr(anchor, 0.5, 0.5) == (ex, ey)


def test_right_anchored_text_grows_leftward():
    """The bug the CLI had: a longer string must not push off the frame."""
    ex, _ = anchor_expr("bottom-right", 0.97, 0.9)
    assert ex.endswith("-tw")


# --- resolution independence ----------------------------------------------


@pytest.mark.parametrize("w,h", [(1280, 720), (1920, 1080), (3840, 2160)])
def test_font_size_scales_with_output(w, h):
    chain, _ = build_chain(
        doc(output=Output(w, h), overlays=[overlay(size=0.05)]), WORK)
    assert f"fontsize={round(h * 0.05)}" in chain


def test_overlay_position_is_resolution_independent():
    """Same document, two resolutions, identical position expressions."""
    o = overlay(x=0.97, y=0.94, anchor="bottom-right")
    a, _ = build_chain(doc(output=Output(1280, 720), overlays=[o]), WORK)
    b, _ = build_chain(doc(output=Output(3840, 2160), overlays=[o]), WORK)
    grab = lambda c: [p for p in c.split(":") if p.startswith(("x=", "y="))]
    assert grab(a) == grab(b)


def test_fit_inside_returns_even_dimensions():
    for dst in [(1920, 1080), (1280, 720), (640, 480)]:
        w, h = fit_inside((1856, 1116), dst)
        assert w % 2 == 0 and h % 2 == 0
        assert w <= dst[0] and h <= dst[1]


# --- text handling --------------------------------------------------------


def test_text_goes_to_a_sidecar_file_not_the_command_line():
    """Inline text cannot survive ffmpeg's two parser levels; see compile.py."""
    chain, files = build_chain(doc(overlays=[overlay(text="hi")]), WORK)
    opts = chain.split("drawtext=")[1].split(":")
    assert any(o.startswith("textfile=") for o in opts)
    assert not any(o.startswith("text=") for o in opts)
    assert files == {WORK / "o1.txt": "hi"}


@pytest.mark.parametrize("nasty", [
    "O'Brien",                    # apostrophe
    "100%",                       # strftime directive
    "back\\slash",
    "colon: here",
    "comma, semi; bracket [x]",
    "multi\nline\ntext",
    "",                           # empty
])
def test_hostile_text_is_never_interpolated_into_argv(nasty):
    chain, files = build_chain(doc(overlays=[overlay(text=nasty)]), WORK)
    assert nasty not in chain or nasty == ""
    assert list(files.values()) == [nasty]


def test_expansion_is_disabled():
    """Without this, '%' in a name is read as a strftime directive."""
    chain, _ = build_chain(doc(overlays=[overlay()]), WORK)
    assert "expansion=none" in chain


def test_multiline_uses_one_drawtext_and_one_plate():
    chain, _ = build_chain(doc(overlays=[overlay(text="a\nb\nc")]), WORK)
    assert chain.count("drawtext=") == 1
    assert chain.count("box=1") == 1


# --- timing ---------------------------------------------------------------


def test_untimed_overlay_has_no_enable_clause():
    chain, _ = build_chain(doc(overlays=[overlay()]), WORK)
    assert "enable=" not in chain


def test_timed_overlay_gets_an_enable_clause():
    chain, _ = build_chain(doc(overlays=[overlay(start=1.0, end=3.0)]), WORK)
    assert "enable='between(t,1.0,3.0)'" in chain


def test_trim_seeks_before_input():
    """-ss after -i decodes and discards; before -i it skips."""
    argv = plan_render(doc(trim=Trim(5.0, 12.0)), Path("i"), Path("o"), WORK).argv
    assert argv.index("-ss") < argv.index("-i")
    assert argv[argv.index("-to") + 1] == "12.000"


def test_preview_seek_is_absolute_source_time():
    """The scrubber spans the whole source and counts from the file's start, so
    a preview measured from the in-point would disagree with the playhead."""
    p = plan_preview(doc(trim=Trim(5.0)), Path("i"), Path("f.png"), WORK, t=2.0)
    assert p.argv[p.argv.index("-ss") + 1] == "2.000"


def test_preview_outside_the_trim_still_renders_that_moment():
    """Trimming decides what the export contains, not what can be looked at."""
    p = plan_preview(doc(trim=Trim(10.0, 15.0)), Path("i"), Path("f.png"), WORK, t=3.0)
    assert p.argv[p.argv.index("-ss") + 1] == "3.000"


def test_preview_and_render_share_the_filter_chain():
    """The WYSIWYG guarantee, asserted rather than assumed."""
    d = doc(crop=Crop(0.1, 0, 0.8, 1), overlays=[overlay()])
    r = plan_render(d, Path("i"), Path("o.mp4"), WORK)
    p = plan_preview(d, Path("i"), Path("f.png"), WORK, t=1.0)
    assert r.argv[r.argv.index("-vf") + 1] == p.argv[p.argv.index("-vf") + 1]


# --- presets --------------------------------------------------------------


def test_gif_is_two_passes_with_a_palette():
    p = plan_render(doc(), Path("i"), Path("o.gif"), WORK, preset="gif")
    assert p.second_pass is not None
    assert "palettegen" in " ".join(p.argv)
    assert "paletteuse" in " ".join(p.second_pass)


def test_gif_caps_fps_and_width():
    p = plan_render(doc(), Path("i"), Path("o.gif"), WORK, preset="gif")
    chain = " ".join(p.argv)
    assert "fps=15" in chain and "min(800,iw)" in chain


def test_silent_source_gets_an_explicit_no_audio_flag():
    p = plan_render(doc(), Path("i"), Path("o.mp4"), WORK, has_audio=False)
    assert "-an" in p.argv and "aac" not in p.argv


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_every_preset_compiles(preset):
    p = plan_render(doc(overlays=[overlay()]), Path("i"),
                    Path("o"), WORK, preset=preset)
    assert p.argv[0] == "ffmpeg"


def test_maximum_quality_is_visually_lossless_not_mathematically_lossless():
    """CRF 0 reproduces the source's own compression artefacts exactly, and
    measured 7.7x the size of a 12 Mb/s input. Nobody means that by 100%."""
    assert quality_value("mp4", 100) == 16
    assert quality_value("webm", 100) == 20


def test_quality_slider_stays_inside_the_usable_range():
    for q in range(0, 101, 5):
        assert 16 <= quality_value("mp4", q) <= 36


def test_quality_slider_is_monotonic():
    values = [quality_value("mp4", q) for q in range(0, 101, 5)]
    assert values == sorted(values, reverse=True)


def test_quality_has_a_plain_language_name():
    assert quality_word(100) == "Visually lossless"
    assert quality_word(0) == "Smaller file"


def test_formats_without_a_quality_knob_get_no_flag():
    assert quality_args(PRESETS["mov"], 50) == []   # ProRes has no CRF
    assert quality_args(PRESETS["gif"], 50) == []


def test_cpu_encoder_emits_crf():
    args = quality_args(PRESETS["mp4"], 100, CPU)
    assert args[:2] == ["-c:v", "libx264"]
    assert "-crf" in args and args[args.index("-crf") + 1] == "16"


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="unknown preset"):
        plan_render(doc(), Path("i"), Path("o"), WORK, preset="avi")


# --- encoder selection ------------------------------------------------------


def test_forcing_cpu_uses_libx264():
    p = plan_render(doc(), Path("i"), Path("o.mp4"), WORK, accel="cpu")
    assert "libx264" in p.argv
    assert p.encoder == "CPU (libx264)"


def test_an_unusable_encoder_falls_back_to_cpu():
    """A machine that loses its GPU should still finish the export."""
    p = plan_render(doc(), Path("i"), Path("o.mp4"), WORK, accel="h264_imaginary")
    assert "libx264" in p.argv


def test_auto_picks_something_that_actually_works():
    from core import encoders
    p = plan_render(doc(), Path("i"), Path("o.mp4"), WORK, accel="auto")
    assert p.encoder in {e.label for e in encoders.available()}


def test_only_mp4_takes_an_encoder():
    for preset in ("webm", "mov", "gif"):
        p = plan_render(doc(), Path("i"), Path("o"), WORK, preset=preset)
        assert p.encoder is None


def test_preview_never_seeks_past_the_last_frame():
    """Seeking to the exact end produced an empty file and a failed render."""
    d = doc()                                   # 70.65s at 60 fps
    p = plan_preview(d, Path("i"), Path("f.jpg"), WORK, t=d.source.duration)
    # Compare the formatted string, since that is what ffmpeg is handed:
    # rounding to milliseconds is what made a one-frame clamp overshoot.
    printed = float(p.argv[p.argv.index("-ss") + 1])
    assert printed < d.duration - 1 / 60


def test_preview_clamps_a_seek_beyond_the_clip():
    d = doc()
    p = plan_preview(d, Path("i"), Path("f.jpg"), WORK, t=9999)
    assert float(p.argv[p.argv.index("-ss") + 1]) < d.duration
