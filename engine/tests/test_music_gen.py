# -*- coding: utf-8 -*-
"""test_music_gen: 音乐轨生成（规格构造 + 多后端）测试。不烧 API 配额。"""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import music_gen as mg
from picwf import music_gen as M


def test_build_spec_m_track():
    s = mg.build_music_spec("M28_anime_jpop", duration_s=30)
    assert s["found"], "M28 应能在 music_tracks 找到"
    assert s["table"] == "music_tracks"
    assert s["bpm"] == [120, 150]
    assert s["duration_s"] == 30
    assert s["style_zh"] and s["style_en"], "中英双语描述都必须有"


def test_build_spec_b_track_backfills():
    """B 类缺 bpm/instruments，应从 music_ref 指向的 M 行补齐。"""
    s = mg.build_music_spec("B06_tragedy_sad")
    assert s["found"] and s["table"] == "bgm_tracks"
    assert s["bpm"], f"B06 应从 music_ref 补齐 bpm, got {s['bpm']}"
    assert s["instruments"], "B06 应补齐 instruments"


def test_spec_english_is_translated():
    """英文描述里不应残留明显中文乐器名。"""
    s = mg.build_music_spec("M1_guoqin_classic")
    en = s["style_en"]
    assert "guqin" in en, en
    assert "instrumental" in en, en
    # 原文中文词不应整串出现在英文描述里
    assert "古琴/琵琶/笛/古筝" not in en, en


def test_spec_zh_mentions_instrumental():
    s = mg.build_music_spec("M3_jazz_swing")
    assert "纯器乐无人声" in s["style_zh"], s["style_zh"]


def test_unknown_track_not_crash():
    s = mg.build_music_spec("M999_not_exist")
    assert s["found"] is False
    assert s["track_key"] == "M999_not_exist"


def test_generate_spec_only_ok():
    """spec_only 是正式能力，必须 ok=True 并带上可手工使用的 style_zh。"""
    r = mg.generate("M28_anime_jpop", backend="spec_only")
    assert r["ok"] is True
    assert r["backend"] == "spec_only"
    assert r["spec"]["style_zh"]


def test_generate_auto_falls_back_to_spec():
    """无 SUNO 配置时 auto 应退到 spec_only 而非报错。"""
    old_key = os.environ.pop("SUNO_API_KEY", None)
    old_base = os.environ.pop("SUNO_API_BASE", None)
    try:
        # 重新载入模块常量以反映环境
        import importlib
        importlib.reload(mg)
        r = mg.generate("M1_guoqin_classic")
        assert r["ok"] is True
        assert r["backend"] == "spec_only"
    finally:
        if old_key is not None:
            os.environ["SUNO_API_KEY"] = old_key
        if old_base is not None:
            os.environ["SUNO_API_BASE"] = old_base
        import importlib
        importlib.reload(mg)


def test_generate_unknown_backend_rejected():
    r = mg.generate("M28_anime_jpop", backend="not_exist")
    assert r["ok"] is False and "未知" in r["error"]


def test_plan_episode_music_full_mode():
    r = mg.plan_episode_music("male_revenge", ep=1, audio_mode="full")
    assert r["ok"] and r["count"] >= 2
    roles = [i["role"] for i in r["items"]]
    assert "bgm" in roles, roles
    # 音乐轨必须有 spec
    music_items = [i for i in r["items"] if i["impl"].startswith(("music_gen.", "bgm_mix."))]
    assert music_items, r["items"]
    for i in music_items:
        assert i["spec"] and i["spec"]["found"], i


def test_plan_episode_music_auto_mode_fewer():
    """auto 模式轨道数不应超过 full 模式。"""
    auto = mg.plan_episode_music("dark_thriller", ep=1, audio_mode="auto")
    full = mg.plan_episode_music("dark_thriller", ep=1, audio_mode="full")
    assert auto["count"] <= full["count"]


def test_plan_multiple_scenarios():
    for sc in ("light_comedy", "daily_romance", "male_revenge", "dark_thriller"):
        r = mg.plan_episode_music(sc, ep=1)
        assert r["ok"], sc
        assert r["count"] >= 1, sc


def test_export_prompt_sheet_writes_file():
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "sheet.json")
        r = mg.export_prompt_sheet(["M1_guoqin_classic", "M28_anime_jpop",
                                    "M999_not_exist"], out_path=out)
        assert r["count"] == 3
        assert os.path.exists(out)
        data = json.load(open(out, encoding="utf-8"))
        assert data["count"] == 3
        assert data["specs"][2]["found"] is False


def test_spec_dedupes_repeated_words():
    """label 与 mood 译成同词时不应重复输出。"""
    s = mg.build_music_spec("B06_tragedy_sad")
    words = [w.strip().lower() for w in s["style_en"].split(",")]
    assert len(words) == len(set(words)), s["style_en"]


def test_mood_hint_overrides():
    s = mg.build_music_spec("M28_anime_jpop", mood_hint="悲伤")
    assert s["mood"] == "悲伤"
    assert "sad emotional" in s["style_en"], s["style_en"]


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
# 本地素材模式（无 SUNO key / MiniMax 音乐端点已停用）
# ---------------------------------------------------------------------------
def _mk_audio(path, dur=3.0):
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency=220:duration={dur}",
                    "-c:a", "libmp3lame", path], check=True, capture_output=True)


def _dur(path):
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def test_find_local_asset_finds_ep_file(tmp_path):
    from picwf.music_gen import find_local_asset

    p = str(tmp_path / "music_ep1.mp3")
    _mk_audio(p, 3.0)
    assert find_local_asset(str(tmp_path), "music", 1) == p


def test_find_local_asset_in_assets_dir(tmp_path):
    from picwf.music_gen import find_local_asset

    d = tmp_path / "assets"
    d.mkdir()
    p = str(d / "bgm_ep2.mp3")
    _mk_audio(p, 3.0)
    assert find_local_asset(str(tmp_path), "bgm", 2) == p


def test_find_local_asset_missing(tmp_path):
    from picwf.music_gen import find_local_asset

    assert find_local_asset(str(tmp_path), "music", 1) == ""


def test_fit_local_asset_loops_to_target(tmp_path):
    """3s 素材配 12s 音轨：必须循环补齐，不是只给 3s。"""
    from picwf.music_gen import fit_local_asset

    src = str(tmp_path / "s.mp3")
    _mk_audio(src, 3.0)
    out = str(tmp_path / "out.mp3")
    r = fit_local_asset(src, 12, out)
    assert r["ok"], r.get("error")
    assert abs(_dur(out) - 12) < 0.6


def test_fit_local_asset_same_path_as_source(tmp_path):
    """素材常就叫 music_ep1.mp3，与输出同路径；ffmpeg 会拒绝 same as Input。"""
    from picwf.music_gen import fit_local_asset

    src = str(tmp_path / "bgm_ep1.mp3")
    _mk_audio(src, 3.0)
    r = fit_local_asset(src, 10, src)
    assert r["ok"], r.get("error")
    assert abs(_dur(src) - 10) < 0.6


def test_generate_local_file_backend(tmp_path):
    from picwf.music_gen import build_music_spec, generate

    src = str(tmp_path / "music_ep1.mp3")
    _mk_audio(src, 3.0)
    spec = build_music_spec("M1", duration_s=8)
    r = generate(spec, backend="auto", out_path=str(tmp_path / "o.mp3"),
                 local_src=src)
    assert r["backend"] == "local_file", "有本地素材时 auto 应走 local_file"
    assert r["ok"] and r["path"]


# ---------------- 本地素材查找（含交付目录 05_音频/） ----------------

def _touch(path, size=4096):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    return path


def test_find_local_asset_exact_name(tmp_path):
    _touch(os.path.join(str(tmp_path), "music", "music_ep1.mp3"))
    hit = M.find_local_asset(str(tmp_path), "music", 1)
    assert hit.endswith("music_ep1.mp3")


def test_find_local_asset_ignores_tiny_file(tmp_path):
    _touch(os.path.join(str(tmp_path), "music", "music_ep1.mp3"), size=10)
    assert M.find_local_asset(str(tmp_path), "music", 1) == ""


def test_find_asset_by_keyword_basic(tmp_path):
    p = _touch(os.path.join(str(tmp_path), "bgm_悬疑压迫.mp3"))
    assert M.find_asset_by_keyword(str(tmp_path), ["悬疑", "压迫"]) == p


def test_find_asset_by_keyword_requires_all_keywords(tmp_path):
    _touch(os.path.join(str(tmp_path), "bgm_悬疑压迫.mp3"))
    assert M.find_asset_by_keyword(str(tmp_path), ["悬疑", "逆袭"]) == ""


def test_find_asset_by_keyword_prefers_shortest_name(tmp_path):
    _touch(os.path.join(str(tmp_path), "bgm_悬疑压迫_加长版_最终_混音v3.mp3"))
    short = _touch(os.path.join(str(tmp_path), "bgm_悬疑压迫.mp3"))
    assert M.find_asset_by_keyword(str(tmp_path), ["悬疑"]) == short


def test_find_asset_by_keyword_scans_delivery_dirs(tmp_path):
    """红剑把资产落 05_音频/ 及 05_音频/特效音/，这两个目录必须在检索路径里。"""
    base = str(tmp_path)
    a = _touch(os.path.join(base, "05_音频", "bgm_热血逆袭.mp3"))
    b = _touch(os.path.join(base, "05_音频", "特效音", "sfx_冲击_打脸.mp3"))
    assert M.find_asset_by_keyword(base, ["热血", "逆袭"]) == a
    assert M.find_asset_by_keyword(base, ["冲击", "打脸"]) == b


def test_find_asset_by_keyword_finds_parent_project_root(tmp_path):
    """资产在 workdir 的上级（项目根），子目录里跑也要找得到。"""
    base = str(tmp_path)
    p = _touch(os.path.join(base, "05_音频", "bgm_情感铺垫.mp3"))
    sub = os.path.join(base, "out", "ep1")
    os.makedirs(sub, exist_ok=True)
    assert M.find_asset_by_keyword(sub, ["情感", "铺垫"]) == p


def test_find_asset_by_keyword_dedup_across_levels(tmp_path):
    """同一目录被向上查找和交付根扫描重复命中时不能重复收集。"""
    base = str(tmp_path)
    p = _touch(os.path.join(base, "05_音频", "music_ep1.mp3"))
    hits = [M.find_asset_by_keyword(base, ["music_ep1"]) for _ in range(3)]
    assert hits == [p, p, p]


def test_find_asset_by_keyword_no_keywords(tmp_path):
    assert M.find_asset_by_keyword(str(tmp_path), []) == ""


def test_find_asset_by_keyword_bad_workdir():
    assert M.find_asset_by_keyword("/nonexistent/xyz", ["a"]) == ""
