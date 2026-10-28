# -*- coding: utf-8 -*-
"""test_voice_track_builder: 配音轨构建（台词解析 + 时间轴对齐）测试。

不依赖真实 TTS：合成环节用 mock 的 voice_tts，重点验证
台词抽取、时间轴排布、溢出检测、降级行为。
"""
import os
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import voice_track_builder as vtb

HAS_FFMPEG = vtb.FFMPEG is not None


def test_parse_normal_line():
    r = vtb.parse_line("周总：这个案子你来做。")
    assert r["character"] == "周总"
    assert r["text"] == "这个案子你来做。"
    assert r["hint"] == "", "无括号时 hint 应为空"


def test_parse_line_with_action_paren():
    """括号里的表演提示应被剥离。"""
    r = vtb.parse_line("林夏（面无表情）：但我没做过这类项目。")
    assert r["character"] == "林夏"
    assert "面无表情" not in r["text"]
    assert r["text"] == "但我没做过这类项目。"


def test_parse_action_line_returns_none():
    """纯动作描述不是台词。"""
    assert vtb.parse_line("周总将一份文件甩到林夏桌上。") is None


def test_parse_empty_and_none():
    assert vtb.parse_line("") is None
    assert vtb.parse_line("   ") is None


def test_parse_halfwidth_colon():
    r = vtb.parse_line("陈姐:还不去？")
    assert r["character"] == "陈姐" and r["text"] == "还不去？"


def _shots():
    return [
        {"index": 1, "raw": "周总：这个案子你来做。", "est_s": 5.0, "emotion": "紧张"},
        {"index": 2, "raw": "周总将一份文件甩到林夏桌上。", "est_s": 3.0, "emotion": "沉淀"},
        {"index": 3, "raw": "林夏（面无表情）：但我没做过这类项目。", "est_s": 4.0,
         "emotion": "压抑"},
        {"index": 4, "raw": "陈姐：还不去？周总要的是坑你。", "est_s": 6.0, "emotion": "温情"},
    ]


def test_extract_lines_skips_action_lines():
    lines = vtb.extract_lines(_shots())
    assert len(lines) == 3, [l["text"] for l in lines]
    chars = [l["character"] for l in lines]
    assert chars == ["周总", "林夏", "陈姐"], chars


def test_extract_lines_timeline_accumulates():
    """台词起始时间应等于前面所有镜头的时长累加（含非台词镜头）。"""
    lines = vtb.extract_lines(_shots())
    assert lines[0]["start_s"] == 0.0
    # 第 1 镜 5s + 第 2 镜 3s（纯动作，无台词但占时间）
    assert lines[1]["start_s"] == 8.0, lines[1]["start_s"]
    assert lines[2]["start_s"] == 12.0, lines[2]["start_s"]


def test_total_duration_sums_est():
    assert vtb.total_duration(_shots()) == 18.0


def test_total_duration_fallback():
    assert vtb.total_duration([], fallback=42.0) == 42.0


def test_emotion_mapped_to_tts_emotion():
    """分镜情绪应映射成 TTS 情绪词。"""
    lines = vtb.extract_lines(_shots())
    import picwf.voice_track_builder as m
    assert m._EMO_MAP.get("紧张") == "fearful"
    assert m._EMO_MAP.get("压抑") == "sad"
    assert lines[0]["emotion"] == "紧张"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg 不可用")
def test_compose_track_places_lines_on_timeline():
    """核心：每句台词必须落在 start_s 对应的时间点，不能首尾相接。"""
    with tempfile.TemporaryDirectory() as td:
        lines = []
        # 三句 1.5s 台词，分别放在 0s / 5.4s / 10.8s
        for i, start in enumerate([0.0, 5.4, 10.8], start=1):
            p = os.path.join(td, f"l{i}.mp3")
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                 "-i", f"sine=frequency={400 + i * 60}:duration=1.5",
                 "-c:a", "libmp3lame", p], check=True, capture_output=True)
            lines.append({"line_id": f"s{i:03d}", "path": p,
                          "start_s": start, "duration_ms": 1500})
        out = os.path.join(td, "voice.mp3")
        r = vtb.compose_track(lines, 16.2, out)
        assert r["ok"], r["error"]
        assert r["line_count"] == 3
        assert 15.5 < r["duration_s"] < 17.0, r["duration_s"]

        # 用 silencedetect 反查有声段位置
        p = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", out,
             "-af", "silencedetect=n=-40dB:d=0.5", "-f", "null", "-"],
            capture_output=True, text=True)
        sil_starts = [float(l.split("silence_start:")[1].split()[0])
                      for l in p.stderr.splitlines() if "silence_start:" in l]
        # 第一段有声在 0-1.5，所以第一个静音起点应接近 1.5
        assert any(1.2 < s < 1.8 for s in sil_starts), sil_starts


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg 不可用")
def test_compose_track_no_usable_lines():
    r = vtb.compose_track([], 10.0, "/tmp/_none.mp3")
    assert r["ok"] is False and "没有可用" in r["error"]


def test_synthesize_lines_degrades_without_backend(monkeypatch):
    """TTS 后端不可用时必须优雅降级，不能抛异常打挂管线。

    不能靠「环境里恰好没有 key」来构造失败：key 一旦落地测试就假通过。
    这里直接注入必失败后端，才真正测到降级路径。
    """
    from picwf.cloud_api import voice_tts

    def _boom(*a, **k):
        return {"ok": False, "path": "", "error": "模拟后端不可用",
                "duration_ms": 0, "backend": "mock"}

    monkeypatch.setattr(voice_tts, "synthesize", _boom)
    lines = vtb.extract_lines(_shots())
    with tempfile.TemporaryDirectory() as td:
        r = vtb.synthesize_lines(lines, td, backend="minimax")
        assert r["ok"] is False
        assert r["failed"] == len(lines)
        assert r["synthesized"] == 0
        for f in r["failures"]:
            assert f["error"], "失败必须有原因"


def test_build_voice_track_no_lines():
    shots = [{"index": 1, "raw": "他走进房间。", "est_s": 3.0}]
    with tempfile.TemporaryDirectory() as td:
        r = vtb.build_voice_track(shots, os.path.join(td, "v.mp3"), workdir=td)
        assert r["ok"] is False
        assert r["line_count"] == 0
        assert "未解析到台词" in r["error"]


def test_build_voice_track_reports_timeline_even_when_tts_fails(monkeypatch):
    """TTS 失败时仍应回报时间轴与台词数，便于诊断而非静默。"""
    from picwf.cloud_api import voice_tts

    monkeypatch.setattr(
        voice_tts, "synthesize",
        lambda *a, **k: {"ok": False, "path": "", "error": "模拟不可用",
                         "duration_ms": 0, "backend": "mock"})
    with tempfile.TemporaryDirectory() as td:
        r = vtb.build_voice_track(_shots(), os.path.join(td, "v.mp3"),
                                  workdir=td, backend="minimax")
        assert r["ok"] is False
        assert r["line_count"] == 3
        assert r["timeline_s"] == 18.0
        assert r["failed"] == 3


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed, failed = [], []
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
            passed.append(fn.__name__)
        except Exception as e:
            print("FAIL", fn.__name__, "->", e)
            failed.append(fn.__name__)
    print(f"\n=== {len(passed)}/{len(fns)} passed, {len(failed)} failed ===")
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------------------
# 角色表解析 + 性别音色 + 括号情绪提示
# ---------------------------------------------------------------------------
_SCRIPT = """# 《测试剧》

**类型：** 职场复仇 / 女性成长

---

## 角色设定

| 角色 | 定位 | 外景描述 |
|------|------|----------|
| 林夏 | 主角，27岁，助理 | 黑色中分微卷，气质冷峻 |
| 周总 | 反派，45岁，部门总监 | 西装革履，油头，金丝眼镜 |
| 陈姐 | 配角，35岁，老员工 | 朴素干练 |

---

## 剧本正文

周总（冷笑）：没做过就学。
"""


def test_parse_characters_extracts_table():
    from picwf.pipeline_runner import parse_characters

    chars = parse_characters(_SCRIPT)
    assert set(chars) == {"林夏", "周总", "陈姐"}
    assert chars["周总"]["age"] == 45


def test_parse_characters_infers_gender():
    """剧本角色名千变万化，靠预设表覆盖不了，必须能推断性别。"""
    from picwf.pipeline_runner import parse_characters

    chars = parse_characters(_SCRIPT)
    assert chars["林夏"]["gender"] == "female", "名字末字「夏」应判女"
    assert chars["陈姐"]["gender"] == "female", "「姐」应判女"
    assert chars["周总"]["gender"] == "male", "「油头」应判男"


def test_parse_characters_no_table():
    from picwf.pipeline_runner import parse_characters

    assert parse_characters("随便一段没有角色表的文本") == {}


def test_pick_voice_by_gender_and_age():
    chars = {"林夏": {"gender": "female", "age": 27},
             "陈姐": {"gender": "female", "age": 35},
             "周总": {"gender": "male", "age": 45},
             "无名": {"gender": "unknown", "age": 0}}
    assert vtb._pick_voice("林夏", chars) == "female"
    assert vtb._pick_voice("陈姐", chars) == "serious", "35 岁女配走御姐音"
    assert vtb._pick_voice("周总", chars) == "male"
    assert vtb._pick_voice("无名", chars) == "male", "推不出性别用成年男声兜底"
    assert vtb._pick_voice("不存在", chars) == "male"


def test_parse_line_keeps_hint():
    r = vtb.parse_line("周总（冷笑）：没做过就学。")
    assert r["character"] == "周总"
    assert r["text"] == "没做过就学。", "括号内容不能念出来"
    assert r["hint"] == "冷笑", "但必须留下当情绪信号"


def test_emotion_from_hint():
    assert vtb._emotion_from_hint("冷笑") == "angry"
    assert vtb._emotion_from_hint("面无表情") == "neutral"
    assert vtb._emotion_from_hint("哽咽") == "sad"
    assert vtb._emotion_from_hint("") == ""


def test_emotion_map_covers_split_enum():
    """_classify_emotion 的输出枚举必须被 _EMO_MAP 全覆盖，否则全降级 neutral。"""
    from picwf.pipeline_runner import _classify_emotion

    need = {"反转", "爆发", "紧张", "铺垫", "推进"}
    missing = need - set(vtb._EMO_MAP)
    assert not missing, f"情绪枚举缺口: {missing}"
    assert _classify_emotion("完全无关的一句话") in vtb._EMO_MAP


def test_hint_overrides_shot_emotion(monkeypatch):
    """括号提示的优先级要高于分镜粗分类的 emotion。"""
    from picwf.cloud_api import voice_tts

    seen = {}

    def _fake(text, **kw):
        seen.setdefault("emo", []).append(kw.get("emotion"))
        return {"ok": False, "path": "", "error": "x", "duration_ms": 0, "backend": "mock"}

    monkeypatch.setattr(voice_tts, "synthesize", _fake)
    lines = [{"line_id": "s1", "character": "周总", "text": "走。",
              "hint": "冷笑", "emotion": "铺垫", "start_s": 0.0,
              "est_s": 5.0, "shot_est_s": 5.0}]
    with tempfile.TemporaryDirectory() as td:
        vtb.synthesize_lines(lines, td, backend="minimax")
    assert seen["emo"] == ["angry"], "hint=冷笑 应压过 emotion=铺垫"
