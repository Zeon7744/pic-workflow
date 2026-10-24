# -*- coding: utf-8 -*-
"""efficiency_planner 资源最优路径测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.efficiency_planner import plan_and_report, to_dashboard
from picwf.model_registry import add_custom_model


def _registry():
    reg: dict = {}
    add_custom_model(reg, "local_wan_q4", kind="video", cloud=False,
                     cost=0.4, speed=0.8, quality=0.78, min_vram_gb=5)
    add_custom_model(reg, "local_flux", kind="image", cloud=False,
                     cost=0.6, speed=1.0, quality=0.82, min_vram_gb=7)
    add_custom_model(reg, "cloud_seedance_2", kind="video", cloud=True,
                     cost=1.8, speed=1.3, quality=0.92, min_vram_gb=0)
    return reg


def test_plan_prefers_best_quality_under_resource_gate():
    reg = _registry()
    out = plan_and_report(reg, profile={"gpu": {"vram_gb": 6}},
                          task={"kind": "video", "quality_min": 0.85, "max_cost": 999})
    assert out["best"]["model_id"] == "cloud_seedance_2"
    assert out["best"]["cloud"] is True
    assert out["gate"]["has_path"] is True


def test_plan_respects_max_cost():
    reg = _registry()
    out = plan_and_report(reg, profile={"gpu": {"vram_gb": 6}},
                          task={"kind": "video", "quality_min": 0.85, "max_cost": 1.0})
    assert out["best"] is None
    assert out["gate"]["has_path"] is False


def test_dashboard_shape_is_exportable():
    reg = _registry()
    out = plan_and_report(reg, profile={"gpu": {"vram_gb": 6}},
                          task={"kind": "video", "quality_min": 0.85})
    dash = out["dashboard"]
    assert dash["best_model"] == "cloud_seedance_2"
    assert dash["path_count"] >= 1
    assert "gate" in dash


def test_pipeline_executors_use_efficiency_plan():
    """8 环节执行器已接 efficiency planner：video_shot 自动择优模型。"""
    import importlib
    pe = importlib.reload(importlib.import_module("picwf.pipeline_executors"))
    wf = {"tier": "T1", "style": "S2_real_cinematic", "scenario": "dark_thriller",
          "episode": 1, "free_vram_gb": 8, "characters": [
              {"name": "叶轻", "role": "主角", "gender": "女性"}]}
    ex = pe.make_executors(wf, workdir="/tmp/pe_eff_test")
    up = {"script_struct": {"shots": [
        {"index": 1, "prompt": "雨夜巷尾", "visual_prompt": "雨夜巷尾"}]},
          "storyboard_prompt": {"shots": [
              {"index": 1, "prompt": "雨夜巷尾"}]}}
    out = ex["video_shot"](up)
    assert out["clip_count"] >= 1
    assert out["efficiency_best_model"], "video_shot 必须给出效率最优模型"
    assert "efficiency_plan" in out
    assert out["efficiency_plan"]["gate"]["has_path"] is True
