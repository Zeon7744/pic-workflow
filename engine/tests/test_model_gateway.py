# -*- coding: utf-8 -*-
"""model_gateway 统一模型接入层测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.model_gateway import choose_backend, gate_decision, available_backend_specs


def test_specs_include_comfyui_adapter_only():
    specs = available_backend_specs()
    assert "comfyui" in specs
    assert specs["comfyui"]["kind"] == "image"
    assert specs["comfyui"]["cloud"] is False


def test_choose_backend_local_image_when_vram_ok():
    d = choose_backend("image", {"gpu": {"vram_gb": 12}})
    assert d["backend"] in {"comfyui", "generic_local"}
    assert d["resource_ok"] is True


def test_choose_backend_cloud_when_local_resource_unfit():
    specs = {
        "comfyui": {"kind": "image", "cloud": False, "priority": 10, "min_vram_gb": 8},
        "cloud_video": {"kind": "image", "cloud": True, "priority": 30},
        "mock": {"kind": "*", "cloud": False, "priority": 90, "min_vram_gb": 1},
    }
    d = choose_backend("image", {"gpu": {"vram_gb": 4}}, specs)
    assert d["cloud"] is True
    assert d["backend"] == "cloud_video"


def test_gate_decision_quality_failure_blocks_pass():
    decision = {"backend": "mock", "resource_ok": True, "reason": "resource_ok_local_first"}
    g = gate_decision(decision, quality_score=0.62, quality_threshold=0.8)
    assert g["pass"] is False
    assert g["quality_ok"] is False
    assert g["reason"] == "quality_gate_failed"
