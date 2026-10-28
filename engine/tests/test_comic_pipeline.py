# -*- coding: utf-8 -*-
"""test_comic_pipeline: 漫剧三环节链路串联（角色卡 → 分镜 → 运动）验证。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import comic_drama_pipeline as cdp
from picwf import comic_drama_workflow as cdw


def test_pipeline_t3_full_ok():
    r = cdp.render_pipeline(tier="T3")
    assert r["ok"], f"T3 链路应跑通, blocking={r['blocking']}"
    assert len(r["stages"]) == 3
    names = [s["stage"] for s in r["stages"]]
    assert names == ["character_sheet", "storyboard", "motion"], names


def test_pipeline_stage_counts():
    r = cdp.render_pipeline(tier="T3")
    by = {s["stage"]: s for s in r["stages"]}
    assert by["character_sheet"]["count"] == 4, "角色卡应出 4 个变体"
    assert by["storyboard"]["count"] == 3, "分镜应出 3 帧"
    assert by["motion"]["count"] == 1, "运动应出 1 个片段"


def test_pipeline_links_carry_outputs():
    """核心：上游真实输出必须被接进下游输入。"""
    r = cdp.render_pipeline(tier="T3")
    by = {s["stage"]: s for s in r["stages"]}
    # 角色卡首图 -> 分镜 character_ref
    assert by["storyboard"]["prompts"][0]["8"]["inputs"]["image"] == "char_v0.png"
    # 分镜首帧 -> 运动 first_frame
    assert by["motion"]["prompts"][0]["8"]["inputs"]["image"] == "story_f0.png"
    # 分镜尾帧 -> 运动 last_frame
    assert by["motion"]["prompts"][0]["8b"]["inputs"]["image"] == "story_f2.png"


def test_pipeline_no_placeholder_left():
    r = cdp.render_pipeline(tier="T3")
    for st in r["stages"]:
        for p in st["prompts"]:
            issues = cdw.validate_rendered(p)
            assert not issues, f"{st['stage']} 残留问题: {issues}"


def test_pipeline_low_tier_blocks_with_reason():
    """T1 只有角色卡：链路应明确报断点，而不是静默成功。"""
    r = cdp.render_pipeline(tier="T1")
    assert not r["ok"], "T1 跑不动完整链路"
    assert not r["can_instantiate"]
    text = " ".join(r["blocking"])
    assert "storyboard" in text and "motion" in text, r["blocking"]
    # 但角色卡本身应可用
    assert r["stages"][0]["valid"], "T1 角色卡应可用"


def test_pipeline_storyboard_seed_increments():
    """多帧之间 seed 必须递增，否则产出同一张图。"""
    r = cdp.render_pipeline(tier="T3")
    story = [s for s in r["stages"] if s["stage"] == "storyboard"][0]
    seeds = [int(p["5"]["inputs"]["seed"]) for p in story["prompts"]]
    assert len(set(seeds)) == len(seeds), f"seed 应各不相同, got {seeds}"
    assert seeds == sorted(seeds), f"seed 应递增, got {seeds}"


def test_pipeline_custom_overrides_flow_through():
    """自定义角色描述必须真的进入角色卡 prompt。"""
    r = cdp.render_pipeline(
        tier="T3",
        character_overrides={"character_prompt": "cyberpunk android girl, red eyes"})
    char = [s for s in r["stages"] if s["stage"] == "character_sheet"][0]
    text = char["prompts"][0]["2"]["inputs"]["text"]
    assert "cyberpunk android girl" in text, text


def test_pipeline_variant_filenames_distinct():
    r = cdp.render_pipeline(tier="T3")
    char = [s for s in r["stages"] if s["stage"] == "character_sheet"][0]
    assert char["outputs"] == ["char_v0.png", "char_v1.png",
                               "char_v2.png", "char_v3.png"], char["outputs"]


def test_pipeline_summary_readable():
    r = cdp.render_pipeline(tier="T3")
    s = cdp.pipeline_summary(r)
    assert "character_sheet" in s and "storyboard" in s and "motion" in s


def test_stage_tier_unsupported_helper():
    assert cdp.stage_tier_unsupported("motion", "T1")
    assert not cdp.stage_tier_unsupported("character_sheet", "T1")
    assert not cdp.stage_tier_unsupported("motion", "T4")


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
