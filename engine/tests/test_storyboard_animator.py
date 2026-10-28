# -*- coding: utf-8 -*-
"""静图动态化（animatic）测试：agnes 视频配额不足时的兜底画面路径。"""
import os
import subprocess
import pytest

from picwf import storyboard_animator as sa


def _has_ffmpeg():
    return bool(sa.FFMPEG)


def _make_png(path, w=360, h=640):
    subprocess.run([sa.FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=c=0x334455:s={w}x{h}:d=1",
                    "-frames:v", "1", path], check=True)
    return path


def test_motion_map_covers_shot_types():
    assert sa.pick_motion("远景") == "pan_right"
    assert sa.pick_motion("特写") == "push_in"
    assert sa.pick_motion("空镜") == "pull_out"
    assert sa.pick_motion("") in ("push_in", "pan_right", "pull_out", "pan_left")


def test_pick_motion_rotates_for_unknown_shot_type():
    got = [sa.pick_motion("", i) for i in range(4)]
    assert len(set(got)) == 4


def test_pick_motion_varies_repeated_push_in():
    # 连续特写不能全用同一个动作，第 3 个要换
    got = [sa.pick_motion("特写", i) for i in range(3)]
    assert got[0] == got[1] == "push_in"
    assert got[2] == "pull_out"


def test_animate_missing_image_returns_error():
    r = sa.animate_still("/no/such/file.png", "/tmp/_x.mp4", 3.0)
    assert r["ok"] is False and r["path"] == ""
    assert "不存在" in r["error"]


@pytest.mark.skipif(not _has_ffmpeg(), reason="需要 ffmpeg")
def test_animate_duration_matches_request(tmp_path):
    src = _make_png(str(tmp_path / "a.png"))
    out = str(tmp_path / "a.mp4")
    r = sa.animate_still(src, out, 4.0, motion="push_in", w=360, h=640)
    assert r["ok"] is True and os.path.isfile(out)
    assert abs(r["duration_s"] - 4.0) < 0.35


@pytest.mark.skipif(not _has_ffmpeg(), reason="需要 ffmpeg")
def test_animate_output_size_is_target(tmp_path):
    src = _make_png(str(tmp_path / "b.png"), 200, 200)
    out = str(tmp_path / "b.mp4")
    r = sa.animate_still(src, out, 2.0, w=360, h=640)
    assert r["ok"] is True
    probe = subprocess.run([sa.FFPROBE, "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of",
                            "csv=p=0", out], capture_output=True, text=True)
    w, h = [int(x) for x in probe.stdout.strip().split(",")[:2]]
    assert (w, h) == (360, 640)
