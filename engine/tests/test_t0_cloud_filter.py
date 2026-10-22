# -*- coding: utf-8 -*-
"""T0 无独显纯云端档选模回归测试。

锁死 bug：T0 档出图/出视频必须 cloud 优先，不能残留本地 SDXL/flux 重模型。
"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from picwf import workflow_gen as wg
from picwf import tier_scoring as ts

MATRIX = str(REPO.parent.parent / "config" / "matrix.yaml")

def _t0_workflow(style="S1_anime_jp"):
    return wg.generate_workflow(tier="T0", scenario="light_comedy",
                                ep=3, audio_mode="auto", style=style)

def test_n95_judged_t0():
    # N95：无独显（集显 128MB 记 0），32GB 内存
    res = ts.match_tier({"gpu": {"vram_gb": 0, "arch": "None", "fp8_support": False},
                         "ram": {"ram_gb": 31.7}})
    assert res["tier"] == "T0", f"N95 应判 T0，实际 {res['tier']}"

def test_t0_image_node_cloud_first():
    # T0 出图节点首项必须是云端（不再残留 sdxl/flux 本地 lora）
    w = _t0_workflow()
    nd = next(n for n in w["nodes"] if n["id"] == "character_image")
    impl = nd["primary"]["impl"]
    assert ("cloud" in impl or "seedream" in impl or "api" in impl), \
        f"T0 出图应云端优先，实际 {impl}"
    # 画风链里本地重模型仍保留作兜底，但不应在首项
    local_first = nd["fallback_chain"][0]["impl"]
    assert not (local_first.startswith("sdxl") or local_first.startswith("flux")), \
        f"T0 出图链首不应是本地重模型，实际 {local_first}"

def test_t0_video_node_cloud_first():
    w = _t0_workflow()
    nd = next(n for n in w["nodes"] if n["id"] == "video_shot")
    impl = nd["primary"]["impl"]
    assert ("cloud" in impl or "kling" in impl), f"T0 出视频应云端优先，实际 {impl}"

def test_t1_local_gguf_unchanged():
    # 回归：T1（1060 本地 6GB）出图/出视频仍走本地，不受 T0 过滤影响
    w = wg.generate_workflow(tier="T1", scenario="male_revenge", ep=4, audio_mode="auto")
    i = {n["id"]: n["primary"]["impl"] for n in w["nodes"]}
    assert "sdxl" in i["character_image"] or "flux" in i["character_image"], \
        f"T1 出图应保持本地，实际 {i['character_image']}"
    assert "gguf" in i["video_shot"] or "wan13b" in i["video_shot"], \
        f"T1 出视频应保持本地量化，实际 {i['video_shot']}"
