# -*- coding: utf-8 -*-
"""accessibility_layer 行为测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.accessibility_layer import mode_params, cost_visibility, friendly_failure


def test_mode_params_scale_by_level():
    b = mode_params("beginner", {"tier": "T1"})
    p = mode_params("pro", {"tier": "T1"})
    e = mode_params("expert", {"tier": "T1"})
    assert b["params"]["steps"] < p["params"]["steps"] < e["params"]["steps"]
    assert b["params"]["quality_target"] < e["params"]["quality_target"]


def test_cost_visibility_exports_options():
    plan = {"best": {"cost": 0.4, "estimated_vram_gb": 6, "speed": 0.8},
            "paths": [
                {"model_id": "wan13b_gguf_q4_offload_480", "cost": 0.4,
                 "estimated_vram_gb": 6, "speed": 0.8, "cloud": False},
                {"model_id": "cloud_seedance_2", "cost": 1.8,
                 "estimated_vram_gb": 0, "speed": 1.3, "cloud": True},
            ]}
    out = cost_visibility(plan)
    assert out["primary"]["model_id"] == "wan13b_gguf_q4_offload_480"
    assert len(out["options"]) == 2
    assert out["options"][0]["cost_label"] == "本地低成本"
    assert out["options"][1]["cost_label"] == "云端较高成本"


def test_friendly_failure_gives_human_reason_and_fallbacks():
    plan = {"paths": [
        {"model_id": "wan13b_gguf_q4_offload_480", "cloud": False, "resource_ok": True},
        {"model_id": "cloud_seedance_2", "cloud": True, "resource_ok": True},
    ]}
    out = friendly_failure(plan, qa_summary={"total": 4, "failed": 2})
    assert "2/4" in out["reason"]
    assert len(out["fallbacks"]) == 2


def test_pipeline_executors_expose_accessibility_layer():
    import importlib
    pe = importlib.reload(importlib.import_module("picwf.pipeline_executors"))
    wf = {"tier": "T1", "style": "S2_real_cinematic", "scenario": "dark_thriller",
          "episode": 1, "free_vram_gb": 8, "mode": "beginner",
          "local_models": ["wan13b_gguf_q4_offload_480.safetensors"]}
    ex = pe.make_executors(wf, workdir="/tmp/pe_acc_test")
    up = {"storyboard_prompt": {"shots": [{"index": 1, "prompt": "雨夜巷尾"}]}}
    out = ex["video_shot"](up)
    assert "accessibility" in out
    assert out["accessibility"]["mode"] == "beginner"
    assert out["accessibility"]["cost_panel"]["options"], "cost_panel 必须给出可选项"
    assert "failure_panel" in out["accessibility"]


def test_pipeline_executors_normalizes_invalid_mode_to_beginner():
    import importlib
    pe = importlib.reload(importlib.import_module("picwf.pipeline_executors"))
    wf = {"tier": "T1", "style": "S2_real_cinematic", "scenario": "dark_thriller",
          "episode": 1, "free_vram_gb": 8, "mode": "unknown_mode"}
    ex = pe.make_executors(wf, workdir="/tmp/pe_acc_mode_fallback")
    up = {"storyboard_prompt": {"shots": [{"index": 1, "prompt": "雨夜巷尾"}]}}
    out = ex["video_shot"](up)
    assert out["accessibility"]["mode"] == "beginner"
    assert out["accessibility"]["mode_label"] == "新手"


if __name__ == "__main__":
    for name in ("test_mode_params_scale_by_level",
                 "test_cost_visibility_exports_options",
                 "test_friendly_failure_gives_human_reason_and_fallbacks",
                 "test_pipeline_executors_expose_accessibility_layer",
                 "test_pipeline_executors_normalizes_invalid_mode_to_beginner"):
        globals()[name]()
        print(f"PASS {name}")
