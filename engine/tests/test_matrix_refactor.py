# -*- coding: utf-8 -*-
"""matrix.yaml 规范化回归：悬空引用落地 + 档位齐全 + T1 出图降档。"""
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE / "src"))

import yaml
from picwf import config_validator as cv, workflow_gen as wg

MATRIX = str(ENGINE / "config" / "matrix.yaml")


def test_matrix_zero_warnings_zero_errors():
    """悬空引用全部落地，校验器全绿。"""
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    res = cv.validate_matrix(m)
    assert res["errors"] == [], f"matrix 有 error: {res['errors']}"
    assert res["warnings"] == [], f"matrix 有 warning: {res['warnings']}"


def test_style_models_registered_in_nodes():
    """20 画风轨 model 已注册到 character_image/video_shot 的 fallback_chain。"""
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    known = set()
    for n in m["nodes"]:
        for tier_key, levels in n.get("fallback_chain", {}).items():
            for lvl in levels:
                known.add(lvl.get("impl"))
    # 画风轨所有 image_model / video_model 都应在 known
    unregistered = []
    for style, trk in m["style_tracks"].items():
        for dim in ("image_model", "video_model"):
            for impl in (trk.get(dim) or []):
                if impl not in known:
                    unregistered.append(f"{style}.{dim}={impl}")
    assert not unregistered, f"仍有画风 model 未注册到 nodes: {unregistered[:5]}"


def test_all_nodes_cover_mvp_tiers():
    """每个 node 的 fallback_chain 覆盖 T0/T1/T2。"""
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    for n in m["nodes"]:
        covered = set(n.get("fallback_chain", {}).keys())
        assert {"T0", "T1", "T2"} <= covered, \
            f"node {n['id']} 缺档位 {set(['T0','T1','T2']) - covered}"


def test_t1_1060_image_degraded_to_offload():
    """1060 6GB 显存 T1 出图降到 4-5GB 量化/offload 实现（不 OOM）。"""
    w = wg.generate_workflow(tier="T1", scenario="male_revenge", ep=4,
                             audio_mode="auto", free_vram_gb=6)
    nd = next(n for n in w["nodes"] if n["id"] == "character_image")
    need = nd["primary"].get("estimated_vram_need_gb", 0)
    assert need <= 6, f"1060 出图需 {need}GB 超 6GB"
    assert ("gguf" in nd["primary"]["impl"] or "offload" in nd["primary"]["impl"]
            or "cloud" in nd["primary"]["impl"]), \
        f"1060 出图应走量化/offload/云端，实际 {nd['primary']['impl']}"
