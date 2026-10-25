# -*- coding: utf-8 -*-
"""0.5.13 叙事编排层测试：narrative_architect / hook_engine / platform_spec。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from picwf import narrative_architect as na
from picwf import hook_engine as he
from picwf import platform_spec as ps


# ---------------------------------------------------------------------------
# narrative_architect
# ---------------------------------------------------------------------------
def _scenes(n=6):
    return [{"scene_id": "s%d" % (i + 1), "note": "场次%d" % (i + 1)} for i in range(n)]


def test_beat_sheet_structure():
    sheet = na.build_beat_sheet(1, 120, _scenes(), n_payoff=3, n_sweet=1)
    assert sheet["episode_no"] == 1
    assert sheet["beats"], "节拍表不应为空"
    roles = [b["role"] for b in sheet["beats"]]
    assert roles[0] == "hook", "第一拍必须是 hook"
    assert roles[-1] == "cliff", "最后一拍必须是 cliff"
    assert "payoff" in roles and "sweet" in roles
    # 时间轴连续
    for a, b in zip(sheet["beats"], sheet["beats"][1:]):
        assert a["end_s"] == b["start_s"], "节拍时间轴必须连续"
    # 总时长对齐
    assert sheet["beats"][-1]["end_s"] == sheet["target_duration_s"]


def test_payoff_count_and_placement():
    sheet = na.build_beat_sheet(2, 90, _scenes(), n_payoff=3, n_sweet=1)
    kinds = [p["kind"] for p in sheet["payoffs"]]
    assert kinds.count("爽点") == 3
    assert kinds.count("甜点") == 1
    # 爽点必须落在 payoff 角色拍上
    payoff_beats = {b["index"] for b in sheet["beats"] if b["role"] == "payoff"}
    for p in sheet["payoffs"]:
        if p["kind"] == "爽点":
            assert p["beat_index"] in payoff_beats


def test_narrative_qa_blocks_missing_payoff():
    sheet = na.build_beat_sheet(1, 120, _scenes(), n_payoff=0, n_sweet=0)
    qa = na.narrative_qa(sheet)
    assert not qa["passed"]
    codes = [i["code"] for i in qa["issues"]]
    assert "PAYOFF_TOO_FEW" in codes


def test_narrative_qa_passes_with_full_structure():
    sheet = na.build_beat_sheet(1, 120, _scenes(), n_payoff=3, n_sweet=1)
    qa = na.narrative_qa(sheet)
    assert qa["passed"], "完整结构应通过：%s" % qa["issues"]
    assert qa["score"] >= 90
    assert qa["stats"]["n_payoff"] == 3


def test_narrative_qa_flags_close_payoffs():
    sheet = na.build_beat_sheet(1, 120, _scenes(), n_payoff=3, n_sweet=1)
    # 人工把三个爽点挪到 5s 内
    for i, p in enumerate(sheet["payoffs"]):
        if p["kind"] == "爽点":
            p["at_s"] = i * 2
    qa = na.narrative_qa(sheet)
    codes = [i["code"] for i in qa["issues"]]
    assert "PAYOFF_TOO_CLOSE" in codes


def test_design_hook_open_picks_by_tag():
    sheet = na.build_beat_sheet(1, 120, _scenes())
    h = na.design_hook_open(sheet, tags=["mystery", "suspense"])
    assert h["hook_type"] in na.HOOK_TYPES
    assert h["layer_3s"] and h["layer_15s"]
    assert h["window_s"] <= 15
    # 指定类型时按指定走
    h2 = na.design_hook_open(sheet, tags=["mystery"], hook_type="reverse_open")
    assert h2["hook_type"] == "reverse_open"


def test_episode_architect_end_to_end():
    res = na.episode_architect(
        episode_no=3, target_duration_s=100, scenes=_scenes(),
        tags=["revenge", "face_slap"],
        payoff_points=[{"kind": "爽点", "content": "当众打脸"},
                       {"kind": "爽点", "content": "身份反转"},
                       {"kind": "爽点", "content": "签下大单"},
                       {"kind": "甜点", "content": "守护"}],
    )
    assert res["passed"], res["qa"]["issues"]
    assert res["hook"]["hook_type"]
    assert len(res["sheet"]["payoffs"]) == 4


# ---------------------------------------------------------------------------
# hook_engine
# ---------------------------------------------------------------------------
def test_hook_score_strong_vs_weak():
    strong = he.score_hook({
        "hook_type": "reverse_open", "conflict": 1.0, "question": "他怎么做到的",
        "emotion_delta": 0.9, "promise_kept": True,
        "line": "这是翻盘的最后一秒，没人知道林晚是怎么做到的",
    })
    assert strong["score"] >= 80
    assert strong["level"] == "strong"
    assert strong["passed"]

    weak = he.score_hook({
        "hook_type": "nostalgic_hook", "conflict": 0.0, "question": False,
        "emotion_delta": 0.1, "promise_kept": False, "line": "",
    })
    assert weak["score"] < 70
    assert weak["level"] == "weak"
    assert not weak["passed"]
    assert weak["issues"]


def test_hook_score_dims_cover_all_weights():
    r = he.score_hook({"hook_type": "conflict_open"})
    assert set(r["dims"]) == {"conflict", "gap", "emotion", "promise", "clarity"}
    assert abs(sum(r["dims"].values()) / 5.0 - r["score"]) < 25


def test_write_hook_line_and_variants():
    v = he.write_hook_line("conflict_open", {"hero": "林晚", "blocking": "陆家"}, variant=0)
    assert "林晚" in v["line"] and "陆家" in v["line"]
    assert v["hook_type"] == "conflict_open"
    assert v["shot"]

    variants = he.ab_variants("conflict_open", {"hero": "林晚"}, n=3)
    assert len(variants) == 3
    assert [x["variant"] for x in variants] == ["A", "B", "C"]
    assert all("score" in x for x in variants)


def test_hook_gate_blocks_low_score():
    gates = he.hook_gate([
        {"episode_no": 1, "hook_type": "reverse_open", "conflict": 1.0,
         "question": "他到底是怎么做到的", "emotion_delta": 0.9,
         "promise_kept": True, "line": "翻盘就在这一秒"},
        {"episode_no": 2, "hook_type": "nostalgic_hook", "conflict": 0.0,
         "question": False, "emotion_delta": 0.1, "promise_kept": False, "line": ""},
    ])
    assert not gates["passed"]
    assert gates["blocked"] == [2]
    assert gates["n_blocked"] == 1
    assert gates["results"][0]["passed"]


def test_recommend_hook_type_ranking():
    order = he.recommend_hook_type(["mystery", "suspense"])
    assert order[0] in ("suspense_line", "mystery_reveal", "danger_warning",
                        "cold_open_question", "weird_normal", "countdown")


# ---------------------------------------------------------------------------
# platform_spec
# ---------------------------------------------------------------------------
def test_platform_catalog_and_alias():
    assert "redfruit" in ps.list_platforms()
    assert len(ps.list_platforms()) >= 8
    assert ps.get_spec("红果")["platform"] == "redfruit"
    assert ps.get_spec("抖音")["platform"] == "douyin"
    assert ps.get_spec("youtube")["platform"] == "youtube_shorts"
    assert ps.get_spec("不存在的平台") == {}


def test_check_compliance_block_on_ratio_and_duration():
    r = ps.check_compliance(
        {"duration_s": 300, "width": 1920, "height": 1080, "fps": 30,
         "video_bitrate_kbps": 5000, "file_mb": 100, "title_len": 10},
        "redfruit")
    assert not r["passed"]
    fields = {v["field"] for v in r["violations"]}
    assert "duration_s" in fields
    assert "aspect_ratio" in fields
    assert r["suggestions"]


def test_check_compliance_pass_on_valid_media():
    r = ps.check_compliance(
        {"duration_s": 90, "width": 1080, "height": 1920, "fps": 30,
         "video_bitrate_kbps": 5000, "file_mb": 80, "title_len": 12,
         "audio_codec": "aac"},
        "redfruit")
    assert r["passed"], r["violations"]
    assert r["n_block"] == 0


def test_plan_export_contains_ffmpeg_params():
    plan = ps.plan_export({}, "douyin")
    assert plan["platform"] == "douyin"
    ff = plan["ffmpeg"]
    assert "libx264" in ff["c:v"]
    assert "fps=30" in ff["vf"]
    assert plan["aspect_ratio"] == "9:16"
    assert plan["subtitle_safe_area"]["bottom"] >= 0.2


def test_plan_batch_export_marks_blocked():
    res = ps.plan_batch_export(
        {"duration_s": 90, "width": 1080, "height": 1920, "fps": 30,
         "video_bitrate_kbps": 5000, "file_mb": 80, "title_len": 12},
        ["redfruit", "douyin", "bilibili"])
    assert set(res["plans"]) == {"redfruit", "douyin", "bilibili"}
    # bilibili 是横屏，竖屏素材应被 block
    assert "bilibili" in res["blocked"]
    assert "redfruit" in res["publishable"]
    assert "douyin" in res["publishable"]
