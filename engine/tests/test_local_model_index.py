# -*- coding: utf-8 -*-
"""local_model_index 行为测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.local_model_index import (
    index_from_dir_listing,
    build_spec_from_local_file,
    build_registry_with_local,
)
from picwf.efficiency_planner import plan_paths


def test_spec_inference_from_checkpoints_name():
    spec = build_spec_from_local_file("sdxl_v10.safetensors",
                                      source_dir=r"D:\ComfyUI\aki\ComfyUI\models\checkpoints")
    assert spec["id"] == "sdxl_v10"
    assert spec["kind"] == "image"
    assert spec["cloud"] is False
    assert spec["local_source_dir"] == r"D:\ComfyUI\aki\ComfyUI\models\checkpoints"
    assert spec["cost"] < 1.0
    assert spec["quality"] > 0.5


def test_registry_merge_prefers_local():
    base = {"wan13b_gguf_q4_offload_480": {
        "id": "wan13b_gguf_q4_offload_480", "kind": "video",
        "cloud": False, "cost": 0.4, "quality": 0.78, "source": "matrix"}}
    merged = build_registry_with_local(
        ["wan13b_gguf_q4_offload_480.safetensors"],
        source_dir="local",
        base_registry=base,
        prefer_local=True,
    )
    assert merged["wan13b_gguf_q4_offload_480"]["source"] == "local_model_index"


def test_efficiency_planner_can_prefer_local():
    reg = index_from_dir_listing(["wan13b_gguf_q4_offload_480.safetensors",
                                  "cloud_seedance_2.safetensors"],
                                 source_dir="local")
    for mid in reg:
        reg[mid]["cloud"] = ("cloud" in mid)
        reg[mid]["cost"] = 1.0
        reg[mid]["quality"] = 0.9
    plan = plan_paths(reg,
                      profile={"gpu": {"vram_gb": 8}},
                      task={"kind": "video", "quality_min": 0.85,
                            "max_cost": 999.0, "prefer_local": True})
    assert plan["gate"]["has_path"] is True
    assert plan["best"]["model_id"] == "wan13b_gguf_q4_offload_480"
    assert plan["prefer_local"] is True


if __name__ == "__main__":
    for name in ("test_spec_inference_from_checkpoints_name",
                 "test_registry_merge_prefers_local",
                 "test_efficiency_planner_can_prefer_local"):
        globals()[name]()
        print(f"PASS {name}")
