# -*- coding: utf-8 -*-
"""规范化/精准化/完善 三层迭代回归。"""
import sys
from pathlib import Path
import pytest

ENGINE = Path(__file__).resolve().parent.parent          # .../engine
sys.path.insert(0, str(ENGINE / "src"))

from picwf import config_validator as cv
from picwf import qa_scoring as q
from picwf import tier_scoring as ts

MATRIX = str(ENGINE / "config" / "matrix.yaml")


# ---------- 方向 1：config_validator ----------
def test_matrix_current_valid():
    import yaml
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    res = cv.validate_matrix(m)
    # 当前 matrix 无结构性 error（悬空引用只是 warning）
    assert res["errors"] == [], f"当前 matrix 应无 error: {res['errors']}"

def test_validator_catches_missing_tier():
    import yaml
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    m["nodes"][0]["fallback_chain"].pop("T1", None)   # 拔掉 T1
    res = cv.validate_matrix(m)
    assert any("T1" in e for e in res["errors"]), "应抓出缺 T1 档位"

def test_validator_catches_negative_vram():
    import yaml
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    for lvl in m["nodes"][0]["fallback_chain"]["T0"]:
        lvl["estimated_vram_need_gb"] = -5
    res = cv.validate_matrix(m)
    assert any("负数" in e for e in res["errors"]), "应抓出负数 vram_need"

def test_validator_top_key_required():
    res = cv.validate_matrix({"tiers": {}, "nodes": []})   # 缺 version
    assert any("version" in e for e in res["errors"])


# ---------- 方向 2：qa_scoring 档位感知 ----------
def test_tier_aware_threshold():
    m = q.ShotMetrics(consistency_shape=0.82, consistency_style=0.80,
                      continuity_place=0.76, alignment_intent=0.80)
    # 同一镜头：T0 过 / T2 不过（档位越高越严）
    assert q.score_shot(m, tier="T0").passed is True
    assert q.score_shot(m, tier="T2").passed is False

def test_thresh_for_tier():
    t0 = q.thresh_for_tier("T0")
    t2 = q.thresh_for_tier("T2")
    # T2 形变阈值应比 T0 高（更严）
    assert t2["consistency_shape"] > t0["consistency_shape"]

def test_score_shot_backcompat_no_tier():
    # 不传 tier 默认 T1，旧调用不炸
    r = q.score_shot(q.ShotMetrics())
    assert r.route in ("pass", "redo_local", "cloud_refine")


# ---------- 方向 3：__init__ 模块契约 ----------
def test_package_contract_version():
    import picwf
    assert picwf.__version__ == "0.5.1-qa-loop-8stage-integration"
