# -*- coding: utf-8 -*-
"""test_audio_scene_mix: 场景级 BGM 分段 + SFX 对齐测试。"""
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import audio_scene_mix as A

needs_ffmpeg = pytest.mark.skipif(not A.FFMPEG, reason="ffmpeg 不可用")

SHOTS = [
    {"index": 1, "raw": "周总将一份文件甩到林夏桌上。", "est_s": 5.4},
    {"index": 2, "raw": "周总：这个案子你来做。", "est_s": 5.4},
    {"index": 3, "raw": "周总（冷笑）：没做过就学。", "est_s": 5.4},
    {"index": 4, "raw": "林夏独自加班，电脑屏幕映在脸上。", "est_s": 5.4},
    {"index": 5, "raw": "陈姐：还不去？周总要的是坑你。", "est_s": 5.4},
    {"index": 6, "raw": "林夏（抬头）：我不做，谁做？", "est_s": 5.4},
]
ASSETS = {"悬疑压迫": "a.mp3", "情感铺垫": "b.mp3", "热血逆袭": "c.mp3"}


def _tone(path, dur=8.0, hz=220):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency={hz}:duration={dur}",
         "-c:a", "libmp3lame", "-q:a", "5", path],
        check=True, capture_output=True)
    return path


# ---------------- 分段划分 ----------------

def test_auto_segments_groups_adjacent_same_mood():
    segs = A.auto_segments(SHOTS, ASSETS, 32.4)
    assert segs, "应至少切出一段"
    # 相邻同场景必须合并，不能每个镜头一段
    assert len(segs) < len(SHOTS)
    assert segs[0]["start_s"] == 0.0
    assert abs(segs[-1]["end_s"] - 32.4) < 0.01


def test_auto_segments_covers_whole_timeline():
    segs = A.auto_segments(SHOTS, ASSETS, 32.4)
    for a, b in zip(segs, segs[1:]):
        assert abs(a["end_s"] - b["start_s"]) < 0.01, "段落间不能有缝"
    assert all(s["file"] for s in segs)


def test_auto_segments_without_asset_map_returns_empty():
    assert A.auto_segments(SHOTS, {}, 32.4) == []


def test_auto_segments_without_shots_returns_empty():
    assert A.auto_segments([], ASSETS, 32.4) == []


def test_auto_segments_strong_emotion_wins():
    """「我不做，谁做？」同时含悬疑词（冷静）和逆袭意图，必须落逆袭段。"""
    segs = A.auto_segments([SHOTS[-1]], ASSETS, 5.4)
    assert segs[0]["label"] == "热血逆袭"


# ---------------- SFX 排布 ----------------

def test_auto_cues_skips_first_segment():
    segs = A.auto_segments(SHOTS, ASSETS, 32.4)
    cues = A.auto_cues(SHOTS, segs, {"转场": "t.mp3", "冲击": "i.mp3", "压抑": "d.mp3"})
    assert all(c["at_s"] > 0 for c in cues), "片头不该有转场音"


def test_auto_cues_at_segment_boundaries():
    segs = A.auto_segments(SHOTS, ASSETS, 32.4)
    cues = A.auto_cues(SHOTS, segs, {"转场": "t.mp3", "冲击": "i.mp3", "压抑": "d.mp3"})
    starts = {round(float(s["start_s"]), 2) for s in segs[1:]}
    assert {round(c["at_s"], 2) for c in cues} <= starts


def test_auto_cues_picks_impact_for_climax():
    segs = [{"label": "悬疑压迫", "file": "a", "start_s": 0, "end_s": 10},
            {"label": "热血逆袭", "file": "c", "start_s": 10, "end_s": 15}]
    cues = A.auto_cues(SHOTS, segs, {"转场": "t.mp3", "冲击": "i.mp3"})
    assert cues and cues[0]["file"] == "i.mp3"


def test_auto_cues_without_sfx_map_returns_empty():
    segs = A.auto_segments(SHOTS, ASSETS, 32.4)
    assert A.auto_cues(SHOTS, segs, {}) == []


# ---------------- 实际音频拼接 ----------------

@needs_ffmpeg
def test_seg_file_is_exact_duration():
    """mp3 循环裁切必须靠 atrim 精确，只给 -t 会漂（实测 5.4s 做成 7.3s）。"""
    with tempfile.TemporaryDirectory() as td:
        src = _tone(os.path.join(td, "src.mp3"), 8.0)
        dst = os.path.join(td, "seg.m4a")
        assert A._seg_file(src, dst, 5.4)
        assert abs(A._probe(dst) - 5.4) < 0.15


@needs_ffmpeg
def test_build_scene_bed_total_length_matches_video():
    """床长必须严格等于视频总长，短了尾部没音乐，长了会把视频拖长。"""
    with tempfile.TemporaryDirectory() as td:
        src = _tone(os.path.join(td, "src.mp3"), 8.0)
        segs = [{"label": "悬疑压迫", "file": src, "start_s": 0, "end_s": 21.6},
                {"label": "情感铺垫", "file": src, "start_s": 21.6, "end_s": 32.4},
                {"label": "热血逆袭", "file": src, "start_s": 32.4, "end_s": 48.6}]
        out = os.path.join(td, "bed.m4a")
        r = A.build_scene_bed(segs, 48.6, out, os.path.join(td, "_w"))
        assert r["ok"], r.get("error")
        assert abs(A._probe(out) - 48.6) < 0.2


@needs_ffmpeg
def test_build_scene_bed_skips_missing_assets():
    with tempfile.TemporaryDirectory() as td:
        src = _tone(os.path.join(td, "src.mp3"), 8.0)
        segs = [{"file": os.path.join(td, "nope.mp3"), "start_s": 0, "end_s": 5},
                {"file": src, "start_s": 5, "end_s": 10}]
        r = A.build_scene_bed(segs, 10.0, os.path.join(td, "bed.m4a"),
                              os.path.join(td, "_w"))
        assert r["ok"]
        assert abs(A._probe(r["path"]) - 10.0) < 0.2


@needs_ffmpeg
def test_build_sfx_track_length_and_mix():
    with tempfile.TemporaryDirectory() as td:
        a = _tone(os.path.join(td, "a.mp3"), 1.0, 440)
        b = _tone(os.path.join(td, "b.mp3"), 1.0, 880)
        cues = [{"file": a, "at_s": 2.0, "gain_db": -6.0},
                {"file": b, "at_s": 8.0, "gain_db": -3.0}]
        out = os.path.join(td, "sfx.m4a")
        r = A.build_sfx_track(cues, 10.0, out, os.path.join(td, "_w"))
        assert r["ok"], r.get("error")
        assert abs(A._probe(out) - 10.0) < 0.1
        assert r["cues"] == 2


@needs_ffmpeg
def test_build_sfx_track_without_valid_cues_fails_cleanly():
    with tempfile.TemporaryDirectory() as td:
        r = A.build_sfx_track([{"file": os.path.join(td, "no.mp3"), "at_s": 1}],
                              10.0, os.path.join(td, "x.m4a"), td)
        assert r["ok"] is False
        assert r["path"] == ""
