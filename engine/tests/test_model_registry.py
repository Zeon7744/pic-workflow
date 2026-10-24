# -*- coding: utf-8 -*-
"""model_registry + model_gateway v2 测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.model_registry import register_from_matrix, add_custom_model, rank_backends
from picwf.model_gateway import rank_model_candidates


def test_register_from_matrix_covers_styles():
    matrix = {
        "style_tracks": {
            "S1_anime_jp": {
                "image_model": ["sd15_gguf_q4_512_offload", "cloud_api_seedream"],
                "video_model": ["wan13b_gguf_q4_offload_480", "cloud_kling"],
            }
        }
    }
    reg = register_from_matrix(matrix)
    assert "sd15_gguf_q4_512_offload" in reg
    assert "wan13b_gguf_q4_offload_480" in reg
    assert reg["cloud_kling"]["cloud"] is True
    assert reg["sd15_gguf_q4_512_offload"]["kind"] == "image"
    assert reg["wan13b_gguf_q4_offload_480"]["kind"] == "video"


def test_custom_model_can_join_ranking():
    reg = add_custom_model(
        {}, "cloud_seedance_2",
        kind="video", cloud=True,
        cost=1.6, speed=1.2, quality=0.92, min_vram_gb=0,
        notes=["cloud"])
    ranked = rank_backends(reg, {"gpu": {"vram_gb": 6}}, kind="video",
                           strategy={"cost_w": 0.3, "speed_w": 0.3, "quality_w": 0.4})
    assert ranked[0]["id"] == "cloud_seedance_2"
    assert ranked[0]["resource_ok"] is True


def test_rank_model_candidates_works_without_matrix():
    out = rank_model_candidates(
        registry={
            "local_wan_q4": {"id": "local_wan_q4", "kind": "video", "cloud": False,
                             "cost": 0.6, "speed": 0.9, "quality": 0.82,
                             "min_vram_gb": 5, "style_refs": [], "notes": []},
            "cloud_kling": {"id": "cloud_kling", "kind": "video", "cloud": True,
                            "cost": 1.8, "speed": 1.2, "quality": 0.9,
                            "min_vram_gb": 0, "style_refs": [], "notes": []},
        },
        profile={"gpu": {"vram_gb": 4}},
        kind="video",
        top_k=2,
    )
    assert len(out) == 2
    assert out[0]["id"] in {"local_wan_q4", "cloud_kling"}
    assert all("score" in x for x in out)
