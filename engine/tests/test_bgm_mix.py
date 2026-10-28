# -*- coding: utf-8 -*-
"""test_bgm_mix: 混音与对白闪避（ducking）测试。"""
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import bgm_mix

needs_ffmpeg = pytest.mark.skipif(
    not bgm_mix.available(), reason="ffmpeg/ffprobe 不可用")


def _tone(path: str, hz: int, dur: float, amp: float = 0.3) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency={hz}:duration={dur}", "-af", f"volume={amp}",
         "-c:a", "libmp3lame", "-q:a", "5", path],
        check=True, capture_output=True)
    return path


@pytest.fixture
def tone_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td


def test_available_reports_bool():
    assert isinstance(bgm_mix.available(), bool)


def test_probe_duration_missing_file():
    assert bgm_mix.probe_duration("/nonexistent/x.mp3") == 0.0


@needs_ffmpeg
def test_probe_duration_real(tone_dir):
    p = _tone(os.path.join(tone_dir, "a.mp3"), 440, 2.0)
    d = bgm_mix.probe_duration(p)
    assert 1.5 < d < 2.5, d


def test_mix_no_inputs_fails_cleanly():
    r = bgm_mix.mix(out_path="/tmp/_none.mp3")
    assert r["ok"] is False
    assert "可用输入" in r["error"]


def test_mix_missing_paths_ignored():
    """路径不存在时应被忽略，而不是抛异常。"""
    r = bgm_mix.mix(voice_path="/nope/v.mp3", bgm_path="/nope/b.mp3",
                    out_path="/tmp/_none2.mp3")
    assert r["ok"] is False
    assert r["inputs"] == {}


@needs_ffmpeg
def test_mix_voice_plus_bgm_keeps_full_bgm_length(tone_dir):
    """核心回归：对白结束后 BGM 不能被截断（sidechain 侧链需 apad）。"""
    v = _tone(os.path.join(tone_dir, "v.mp3"), 440, 1.0)
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 5.0)
    out = os.path.join(tone_dir, "mix.mp3")
    r = bgm_mix.mix(voice_path=v, bgm_path=b, out_path=out)
    assert r["ok"], r["error"]
    assert r["duration_ms"] >= 4500, f"BGM 被截断: {r['duration_ms']}ms"
    assert os.path.exists(r["path"])


@needs_ffmpeg
def test_mix_bgm_plus_music_two_tracks(tone_dir):
    """双音乐轨时侧链需各自独立，不能复用同一 label。"""
    v = _tone(os.path.join(tone_dir, "v.mp3"), 440, 1.0)
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 4.0)
    m = _tone(os.path.join(tone_dir, "m.mp3"), 330, 4.0)
    out = os.path.join(tone_dir, "mix2.mp3")
    r = bgm_mix.mix(voice_path=v, bgm_path=b, music_path=m, out_path=out)
    assert r["ok"], r["error"]
    assert r["duration_ms"] >= 3500, r["duration_ms"]


@needs_ffmpeg
def test_mix_music_only_no_voice(tone_dir):
    """无对白时不走 ducking 分支，也应正常输出。"""
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 2.0)
    out = os.path.join(tone_dir, "mix3.mp3")
    r = bgm_mix.mix(bgm_path=b, out_path=out)
    assert r["ok"], r["error"]
    assert r["duration_ms"] > 0


@needs_ffmpeg
def test_mix_episode_concat_voice(tone_dir):
    """多句对白应先拼接再与 BGM 混音。"""
    tracks = {}
    for i, hz in enumerate((440, 520, 600), start=1):
        tracks[f"line_{i}"] = _tone(os.path.join(tone_dir, f"l{i}.mp3"), hz, 1.0)
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 5.0)
    out_dir = os.path.join(tone_dir, "out")
    r = bgm_mix.mix_episode(voice_tracks=tracks, bgm_path=b,
                            out_dir=out_dir, ep=1)
    assert r["ok"], r["error"]
    assert r["ep"] == 1
    assert r["voice_concat"] and os.path.exists(r["voice_concat"])
    assert r["duration_ms"] >= 2500, r["duration_ms"]


@needs_ffmpeg
def test_mix_episode_no_voice_only_bgm(tone_dir):
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 2.0)
    r = bgm_mix.mix_episode(voice_tracks={}, bgm_path=b,
                            out_dir=os.path.join(tone_dir, "o2"), ep=3)
    assert r["ok"], r["error"]
    assert r["voice_concat"] == ""


def _mean_volume_db(path: str) -> float:
    """用 ffmpeg volumedetect 测平均音量(dB)。"""
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].split("dB")[0].strip())
    raise AssertionError("volumedetect 未返回 mean_volume")


@needs_ffmpeg
def test_duck_db_maps_to_ratio(tone_dir):
    """duck_db 必须真实接线到 sidechain ratio，而非只进返回值。"""
    v = _tone(os.path.join(tone_dir, "v.mp3"), 440, 1.0)
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 3.0)
    r0 = bgm_mix.mix(voice_path=v, bgm_path=b,
                     out_path=os.path.join(tone_dir, "r0.mp3"), duck_db=0)
    r24 = bgm_mix.mix(voice_path=v, bgm_path=b,
                      out_path=os.path.join(tone_dir, "r24.mp3"), duck_db=-24)
    assert r0["ok"] and r24["ok"], (r0["error"], r24["error"])
    assert r24["duck_ratio"] > r0["duck_ratio"], (r0["duck_ratio"], r24["duck_ratio"])


@needs_ffmpeg
def test_deeper_duck_lowers_output_loudness(tone_dir):
    """压得更深，输出整体响度必须更低（端到端验证参数生效）。"""
    v = _tone(os.path.join(tone_dir, "v.mp3"), 440, 1.0)
    b = _tone(os.path.join(tone_dir, "b.mp3"), 220, 3.0)
    o_light = os.path.join(tone_dir, "light.mp3")
    o_deep = os.path.join(tone_dir, "deep.mp3")
    r1 = bgm_mix.mix(voice_path=v, bgm_path=b, out_path=o_light,
                     duck_db=-3, normalize=False)
    r2 = bgm_mix.mix(voice_path=v, bgm_path=b, out_path=o_deep,
                     duck_db=-24, normalize=False)
    assert r1["ok"] and r2["ok"], (r1["error"], r2["error"])
    loud_light = _mean_volume_db(o_light)
    loud_deep = _mean_volume_db(o_deep)
    assert loud_deep < loud_light, f"深压未降低响度: {loud_deep} vs {loud_light}"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
            passed += 1
        except Exception as e:
            print("FAIL", fn.__name__, "->", e)
            failed.append(fn.__name__)
    print(f"\n=== {passed}/{len(fns)} passed, {len(failed)} failed ===")
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------------------
# 合成成片：音轨必须真挂上 + 片段必须按分镜时长对齐
# 这两条都是实测踩出来的真 bug，不测就会静默产出废片
# ---------------------------------------------------------------------------
def _mk_clip(path, dur=2.0, freq=440):
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc=size=320x240:rate=25:duration={dur}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        check=True, capture_output=True)


def _mean_volume(path):
    import re
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect",
                        "-f", "null", "/dev/null"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    return float(m.group(1)) if m else None


def test_assemble_maps_real_audio_track(tmp_path):
    """成片音轨必须是传入的音频轨，不能是 concat 自带的静音轨。

    实测 bug：不给 -map 时 ffmpeg 选了占位片段自带的静音音轨，成片 -91dB。
    """
    from picwf.assembler import assemble

    clip = str(tmp_path / "c1.mp4")
    _mk_clip(clip, 2.0)
    voice = str(tmp_path / "v.mp3")
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2",
                    "-c:a", "libmp3lame", voice], check=True, capture_output=True)

    out = str(tmp_path / "final.mp4")
    r = assemble([clip], audio_tracks=[voice], out_path=out, workdir=str(tmp_path))
    assert r["ok"] and r["audio_tracks"] == 1
    mv = _mean_volume(out)
    assert mv is not None and mv > -60, f"成片静音了（{mv}dB），音轨没挂上"


def test_assemble_aligns_clip_to_shot_duration(tmp_path):
    """片段时长必须按分镜时长对齐，否则成片与配音整体错位。

    实测 bug：2.02s 的片段拼 10 个 = 20s，配音时间轴是 54s。
    """
    from picwf.assembler import assemble

    clips = []
    for i in range(3):
        p = str(tmp_path / f"c{i}.mp4")
        _mk_clip(p, 2.0)
        clips.append(p)
    out = str(tmp_path / "final.mp4")
    r = assemble(clips, out_path=out, workdir=str(tmp_path),
                 durations=[5.0, 5.0, 5.0])
    assert r["ok"]
    assert abs(r["duration_s"] - 15.0) < 1.0, f"应对齐到 15s，实得 {r['duration_s']}"
