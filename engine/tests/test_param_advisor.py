# -*- coding: utf-8 -*-
"""param_advisor 全模块参数辅助建议测试。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.param_advisor import advise_all, advise_module


def test_advise_all_covers_all_modules():
    out = advise_all({"free_vram_gb": 6, "tier": "T1"})
    assert out["_summary"]["module_count"] == 7
    for m in ["script", "character", "prompt", "video", "audio", "qa", "resource"]:
        assert m in out
        assert "params" in out[m]
        assert "defaults" in out[m]
        assert len(out[m]["params"]) > 0


def test_advise_all_summary_counts_keys():
    out = advise_all({})
    total = sum(len(v["params"]) for k, v in out.items()
                if isinstance(v, dict) and "params" in v)
    assert out["_summary"]["suggested_keys"] == total


def test_video_advisor_low_vram_recommends_q4_480():
    out = advise_module("video", {"tier": "T1", "free_vram_gb": 6})
    d = out["defaults"]
    assert d["model_impl"] == "wan13b_gguf_q4_offload_480"
    assert d["resolution"] == "480p"
    assert d["steps"] == 20


def test_video_advisor_high_vram_recommends_720():
    out = advise_module("video", {"tier": "T3", "free_vram_gb": 16})
    d = out["defaults"]
    assert d["model_impl"] == "wan13b_fp16_720"
    assert d["resolution"] == "720p"
    assert d["steps"] == 28


def test_qa_defaults():
    out = advise_module("qa", {})
    d = out["defaults"]
    assert d["threshold_shape"] == 0.83
    assert d["threshold_style"] == 0.78
    assert d["threshold_place"] == 0.75
    assert d["threshold_intent"] == 0.80
    assert d["auto_requeue"] is True


def test_resource_advisor_claims_cloud_fallback_default_true():
    out = advise_module("resource", {})
    assert out["defaults"]["enable_cloud_fallback"] is True


def test_character_advisor_has_character_fields():
    out = advise_module("character", {"name": "林晚"})
    d = out["defaults"]
    assert d["age_band"] == "25-32岁"
    assert d["hair"] == "黑色中分微卷"
    assert d["outfit"] == "简约都市通勤装"
    # 名字透传
    params = {p["key"]: p["suggested"] for p in out["params"]}
    assert params["name"] == "林晚"


def test_unknown_module_is_flagged():
    out = advise_module("nonexistent", {})
    assert out.get("unknown_module") is True
    assert out["params"] == []
