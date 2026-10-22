# -*- coding: utf-8 -*-
"""各模块迭代回归：CPU offload 预估 / 双维 combo 学习 / 失败类型路由。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from picwf import tier_scoring as ts
from picwf import adaptive as ad
from picwf import downgrade as dg


# ---------- 模块 1：CPU 算力 offload 耗时预估 ----------
def test_tier_unaffected_by_cpu():
    # 档位仍由显存决定，CPU 不影响判档
    assert ts.match_tier({"gpu": {"vram_gb": 0, "arch": "None"},
                         "ram": {"ram_gb": 32}})["tier"] == "T0"
    assert ts.match_tier({"gpu": {"vram_gb": 6, "arch": "Pascal"},
                         "ram": {"ram_gb": 32}})["tier"] == "T1"

def test_offload_elapsed_n95_slow():
    e = ts.estimate_offload_elapsed({"cpu": {"model": "Intel N95", "ghz": 1.7, "cores": 4}}, 10)
    assert e["cpu_class"] == "low_u_series"
    assert e["prefer_cloud"] is True          # N95 本地 offload 太慢，应走云端
    assert e["per_shot_s"] > 100

def test_offload_elapsed_i7_fast():
    e = ts.estimate_offload_elapsed({"cpu": {"model": "i7-8750H", "ghz": 2.2, "cores": 8}}, 10)
    assert e["cpu_class"] == "desktop_high"
    assert e["prefer_cloud"] is False         # i7 桌面级本地 offload 划算


# ---------- 模块 2：剧种×档位 双维聚类 + combo 学习 ----------
def test_cluster_by_scenario():
    rows = [
        {"scenario": "male_revenge", "tier": "T1", "node_id": "video_shot", "model_impl": "x", "combo": {"style": "S9", "music": "M8"}},
        {"tier": "T1", "node_id": "video_shot", "model_impl": "x"},  # 无 scenario → 默认 light_comedy
    ]
    b = ad.cluster_history_by_scenario(rows)
    assert any(k.startswith("male_revenge::T1") for k in b)
    assert any(k.startswith("light_comedy::T1") for k in b)

def test_combo_learn_picks_low_oom():
    rows = [
        {"scenario": "male_revenge", "tier": "T1", "shot_elapsed_s": 60,
         "oom_degraded": False, "combo": {"style": "S9", "music": "M8", "voice": "V4", "bgm": "B18"}},
        {"scenario": "male_revenge", "tier": "T1", "shot_elapsed_s": 60,
         "oom_degraded": False, "combo": {"style": "S9", "music": "M8", "voice": "V4", "bgm": "B18"}},
        {"scenario": "male_revenge", "tier": "T1", "shot_elapsed_s": 60,
         "oom_degraded": True, "combo": {"style": "S20", "music": "M1", "voice": "V1", "bgm": "B1"}},
    ]
    learned = ad.combo_learn(rows)
    cell = learned["male_revenge::T1"]
    # 无 OOM 的 S9 combo 应为 best（样本 2 条 vs 1 条 OOM）
    assert cell["best_combo"]["style"] == "S9"

def test_apply_combo_learn_writes_matrix():
    import yaml, copy
    matrix = {"emotion_arc_map": {}}
    rows = [
        {"scenario": "light_comedy", "tier": "T1", "shot_elapsed_s": 30,
         "oom_degraded": False, "combo": {"style": "S1", "music": "M1", "voice": "V1", "bgm": "B1"}},
        {"scenario": "light_comedy", "tier": "T1", "shot_elapsed_s": 30,
         "oom_degraded": False, "combo": {"style": "S1", "music": "M1", "voice": "V1", "bgm": "B1"}},
    ]
    learned = ad.combo_learn(rows)
    out = ad.apply_combo_learn_to_matrix(matrix, learned)
    assert "light_comedy__T1" in out["emotion_arc_map"]


# ---------- 模块 3：downgrade 失败类型路由 ----------
def _node():
    return {"id": "video_shot", "current_level": 0,
            "fallback_chain": [
                {"impl": "wan13b_fp16", "estimated_vram_need_gb": 9},
                {"impl": "wan13b_gguf_q4_offload_480", "estimated_vram_need_gb": 5},
                {"impl": "cloud_kling", "estimated_vram_need_gb": 0}]}

def test_route_oom_jumps_level():
    r = dg.route_fallback(_node(), free_vram_gb=2, failure="oom", oom_happened=True)
    assert r["level"] == 1
    assert r["impl_name"] == "wan13b_gguf_q4_offload_480"

def test_route_timeout_picks_faster_same_tier():
    # 超时：当前档内找更快实现（量化/offload），不跳最末云端
    node = {"id": "video_shot", "current_level": 0,
            "fallback_chain": [
                {"impl": "wan13b_fp16", "estimated_vram_need_gb": 9},
                {"impl": "wan13b_gguf_q4_offload_480", "estimated_vram_need_gb": 5},
                {"impl": "cloud_kling", "estimated_vram_need_gb": 0}]}
    r = dg.route_fallback(node, free_vram_gb=5, failure="timeout", timeout_s=120)
    assert r["impl_name"] == "wan13b_gguf_q4_offload_480"   # 同档内量化最快，不跳云端
    assert "timeout" in r["reason"]

def test_route_quality_keeps_impl_tighten():
    r = dg.route_fallback(_node(), free_vram_gb=9, failure="quality")
    assert r["level"] == 0
    assert r["impl_name"] == "wan13b_fp16"     # 保留当前实现
    assert r["adjust"]["keep_impl"] is True
    assert r["adjust"]["steps_scale"] == 0.8    # 收紧参数

def test_degrade_plan_by_failure():
    plan = dg.build_degrade_plan_by_failure(_node())
    assert plan["failure_routes"]["oom"]
    assert plan["failure_routes"]["quality"]
