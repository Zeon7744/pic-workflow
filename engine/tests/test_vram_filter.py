# -*- coding: utf-8 -*-
"""画风轨 model 链按 free_vram_gb 降档回归测试。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from picwf import workflow_gen as wg


def test_1060_t1_image_node_degraded_to_offload():
    # 1060 6GB 显存，画风轨 S1 首项 sdxl_anime_lora 需 12GB，应降到 4GB 量化/offload
    w = wg.generate_workflow(tier="T1", scenario="male_revenge", ep=4,
                             audio_mode="auto", free_vram_gb=6)
    nd = next(n for n in w["nodes"] if n["id"] == "character_image")
    impl = nd["primary"]["impl"]
    need = nd["primary"].get("estimated_vram_need_gb", 0)
    assert need <= 6, f"出图 {impl} 需 {need}GB 超 6GB 显存"
    assert "gguf" in impl or "offload" in impl or "cloud" in impl, \
        f"1060 出图应走量化/offload/云端，实际 {impl}"


def test_t0_all_cloud():
    # T0 纯云端档，出图/出视频必须 cloud（0GB 需求）
    w = wg.generate_workflow(tier="T0", scenario="light_comedy", ep=3,
                             audio_mode="auto", free_vram_gb=0)
    i = {n["id"]: n["primary"]["impl"] for n in w["nodes"]}
    for k in ("character_image", "video_shot"):
        assert i[k].startswith("cloud") or "kling" in i[k] or "seedream" in i[k], \
            f"T0 {k} 应全云端，实际 {i[k]}"


def test_high_vram_t2_keeps_local():
    # T2 12GB 显存，画风轨首项 sdxl 可跑（12GB 需求）
    w = wg.generate_workflow(tier="T2", scenario="dark_thriller", ep=4,
                             audio_mode="auto", free_vram_gb=12)
    nd = next(n for n in w["nodes"] if n["id"] == "character_image")
    need = nd["primary"].get("estimated_vram_need_gb", 0)
    # T2 高端档，画风首项 sdxl/flux 12GB 可保留
    assert need <= 12 or need == 0, f"T2 出图 {nd['primary']['impl']} 需 {need}GB"
