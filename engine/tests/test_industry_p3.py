# -*- coding: utf-8 -*-
"""cross_episode_memory / transition_design / multimodal_qa 单测（行业前3能力）。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


# ---------------- cross_episode_memory ----------------

def test_episode_anchor_and_gap_detects_unstable():
    from picwf import cross_episode_memory as cm
    a1 = cm.build_episode_anchor({"name": "沈昭", "face_emb": [0.1, 0.2], "skeleton": "female_slim",
                                  "temperament": "冷峻", "hair": "及腰黑长直", "outfit": "黑西装"}, ep=1)
    a2 = cm.build_episode_anchor({"name": "沈昭", "face_emb": [0.1, 0.2], "skeleton": "female_slim",
                                  "temperament": "冷峻", "hair": "及腰黑长直", "outfit": "红色礼服"}, ep=10)
    audit = cm.anchor_gap_audit(a1, a2)
    # outfit 变了但未声明 -> warning 漂移
    assert any(d["field"] == "outfit" and d["severity"] == "warning" for d in audit["drifts"])
    assert audit["face_score"] == 1.0
    assert not audit["is_drift"]  # 无 critical


def test_explicit_change_not_drift():
    from picwf import cross_episode_memory as cm
    a1 = cm.build_episode_anchor({"name": "沈昭", "hair": "黑长直", "outfit": "黑西装", "temperament": "冷峻"}, ep=1)
    a2 = cm.build_episode_anchor({"name": "沈昭", "hair": "染成金色", "outfit": "黑西装", "temperament": "冷峻"}, ep=5,
                                  explicit_changes={"hair": "染成金色"})
    audit = cm.anchor_gap_audit(a1, a2)
    # 发型变化已声明 -> 不 drift
    assert not any(d["field"] == "hair" for d in audit["drifts"])
    assert "hair" in audit["stable"] or "hair(declared)" in audit["stable"]


def test_immutable_drift_is_critical():
    from picwf import cross_episode_memory as cm
    a1 = cm.build_episode_anchor({"name": "沈昭", "face_emb": [1.0, 0.0], "temperament": "冷峻"}, ep=1)
    a2 = cm.build_episode_anchor({"name": "沈昭", "face_emb": [0.0, 1.0], "temperament": "活泼"}, ep=10)
    audit = cm.anchor_gap_audit(a1, a2)
    # 脸（用默认 0 相似度）+ 气质 不可变 -> critical -> is_drift
    assert audit["is_drift"] is True


def test_bible_and_inject():
    from picwf import cross_episode_memory as cm
    chars = [{"name": "沈昭", "face_emb": [1.0, 0.0], "skeleton": "female_slim",
              "temperament": "冷峻", "hair": "黑长直", "outfit": "黑西装"}]
    anchors = [
        cm.build_episode_anchor({"name": "沈昭", "face_emb": [1.0, 0.0], "skeleton": "female_slim",
                                 "temperament": "冷峻", "hair": "黑长直", "outfit": "黑西装"}, ep=1),
        cm.build_episode_anchor({"name": "沈昭", "face_emb": [1.0, 0.0], "skeleton": "female_slim",
                                 "temperament": "冷峻", "hair": "黑长直", "outfit": "红裙"}, ep=5,
                                 explicit_changes={"outfit": "红裙"}),
    ]
    bible = cm.build_long_term_bible(chars, anchors)
    b = bible["bible"]["沈昭"]
    assert b["anchor_count"] == 2
    assert any(e["field"] == "outfit" for e in b["evolution"])
    # 注入：后续集未声明变化时，outfit 回填基线
    ep_states = [{"name": "沈昭", "outfit": "漂移了", "hair": "漂移", "_explicit_changes": {}}]
    fixed = cm.inject_bible_into_episodes(bible, ep_states)
    assert fixed[0]["outfit"] == "黑西装"  # 回填基线


# ---------------- transition_design ----------------

def test_transition_pick_and_plan():
    from picwf import transition_design as td
    shots = [
        {"index": 1, "scene": "大厅", "action": "冲", "dialogue": ""},
        {"index": 2, "scene": "大厅", "action": "冲", "dialogue": ""},
        {"index": 3, "scene": "小巷", "action": "躲", "dialogue": ""},
    ]
    plan = td.plan_transitions(shots, emotion_arc=["tense", "neutral"])
    assert len(plan) == 2
    assert plan[0]["type"] in ("hard_cut", "match_cut")  # 同场景动作
    # 场景突变
    assert plan[1]["type"] in ("whip_pan", "mask_wipe", "hard_cut")


def test_transition_qa_flags_repeat_and_dense():
    from picwf import transition_design as td
    shots = [{"index": i, "scene": "s" if i % 2 else "t", "action": "走"} for i in range(1, 7)]
    plan = td.plan_transitions(shots, emotion_arc=["warm"] * 5)
    qa = td.transition_qa(plan)
    # 有 repeat / dense / mismatch 任一 issue 收集
    assert isinstance(qa["issues"], list)
    assert "density_max" in qa and "passed" in qa


# ---------------- multimodal_qa ----------------

def test_lip_sync_pass_and_fail():
    from picwf import multimodal_qa as mq
    good = mq.lip_sync_qa([{"t": 1.0, "offset_s": 0.05}, {"t": 2.0, "offset_s": 0.08}])
    assert good["passed"] and good["score"] == 1.0
    bad = mq.lip_sync_qa([{"t": 1.0, "offset_s": 0.3}])
    assert not bad["passed"] and len(bad["issues"]) == 1


def test_av_sync_and_rhythm():
    from picwf import multimodal_qa as mq
    av = mq.av_sync_qa([{"t": 1.0, "offset_s": 0.1, "label": "门声"}])
    assert av["passed"]
    # 节奏卡点：动作 1.0s，节拍 1.0 -> 完美
    r1 = mq.rhythm_qa([{"t": 1.0}], beat_times=[0.0, 1.0, 2.0])
    assert r1["passed"] and r1["snaps"][0]["offset_s"] == 0.0
    # 动作 1.3，节拍 1.0 -> 偏 0.3 = 阈值，不过（>0.3 才算，等于则过）
    r2 = mq.rhythm_qa([{"t": 1.4}], beat_times=[0.0, 1.0, 2.0])
    assert r2["snaps"][0]["offset_s"] == 0.4


def test_aggregate_blocking_on_lip_fail():
    from picwf import multimodal_qa as mq
    lip_fail = mq.lip_sync_qa([{"t": 1.0, "offset_s": 0.5}])
    av_ok = mq.av_sync_qa([])
    r_ok = mq.rhythm_qa([], [])
    e_ok = mq.emotion_align_qa([], [])
    agg = mq.aggregate_multimodal_qa(lip_fail, av_ok, r_ok, e_ok)
    assert agg["blocking"] is True
    assert agg["passed"] is False
    assert agg["dims"]["lip"] < 1.0
