# -*- coding: utf-8 -*-
"""公开前沿迭代单测：时间轴化 + 首尾帧传递 + 特征锁定 + 人脸质检。

比 ComfyUI 原生工作流更优的突出点：时间戳分镜、时长反推动作量、
运镜打架审计、骨架先锁再注角色、换装检测、人脸相似度打分。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.shot_choreo import (time_axis, single_motion_lock,
    motion_consistency_audit, suggest_split, craft_time_axis_shot, _action_cap)
from picwf.continuity import (chain_shots, teleport_audit, outfit_change_audit,
    apply_character_after_skeleton, lock_skeleton_first)
from picwf.character_consistency import lock_char_traits, face_similarity_gate


# --- 时间轴化分镜（比 ComfyUI 更优的突出点）---
def test_time_axis_timestamps():
    p = time_axis([{"start_s": 0, "end_s": 4, "who": "男人", "where": "走廊",
                    "action": "行走", "motion": "跟"}])
    assert p.startswith("0-4s")


def test_single_motion_lock():
    assert "推" in single_motion_lock("推") and "环绕" not in single_motion_lock("推")


def test_motion_conflict_audit():
    v = motion_consistency_audit(["特写推近，同时环绕"])
    assert v and v[0]["index"] == 1


def test_no_conflict_passes():
    assert motion_consistency_audit(["中景固定机位"]) == []


# --- 时长反推动作量 ---
def test_action_cap_grows_with_time():
    assert _action_cap(5) == 1 and _action_cap(15) == 4


def test_suggest_split_when_overflow():
    adv = suggest_split({"est_s": 10, "actions": 4})
    assert adv and "拆" in adv
    assert suggest_split({"est_s": 10, "actions": 2}) is None


def test_craft_time_axis_segmentation():
    r = craft_time_axis_shot({"est_s": 12, "raw": "x", "motion": "推"})
    assert len(r["segments"]) == 3 and r["time_axis"]


# --- 首尾帧传递 + 骨架先锁再注角色 ---
def test_skeleton_carry_from_prev():
    locked = lock_skeleton_first({"prompt": "x"},
                                  {"pose": "站立", "position": "走廊中", "facing": "前"})
    assert "承接自上一镜" in locked["prompt"] and locked["skeleton_locked"]


def test_chain_shots_propagates_state():
    shots = [
        {"index": 1, "pose": "站", "position": "A", "state_after":
            {"pose": "坐", "position": "B", "facing": "左"}},
        {"index": 2, "pose": "坐", "position": "B", "state_after":
            {"pose": "站", "position": "C"}},
    ]
    chained = chain_shots(shots)
    assert chained[1]["carry_from_prev"]["pose"] == "坐"


def test_character_must_come_after_skeleton():
    import pytest
    with pytest.raises(ValueError):
        apply_character_after_skeleton([{"index": 1, "raw": "x"}],
                                       [{"name": "林晚"}])  # 没锁骨架


def test_teleport_audit():
    v = teleport_audit([{"scene": "A", "position": "左"},
                        {"scene": "A", "position": "右"}])
    assert v and "瞬移" in v[0]["hint"]


def test_outfit_change_audit():
    v = outfit_change_audit([{"outfit": "A"}, {"outfit": "B", "outfit_change": True}])
    assert v and v[0]["from_outfit"] == "A"


# --- 特征词逐字锁定（禁缩写）---
def test_lock_char_traits_vague_words():
    r = lock_char_traits({"name": "林晚", "hair": "长发", "age_band": "年轻"})
    assert r["fixes"] and all(f["field"] in ("hair", "age_band") for f in r["fixes"])
    assert "长发" not in r["locked"]["hair"] or "及腰" in r["locked"]["hair"]


def test_face_similarity_gate():
    g = face_similarity_gate([0.9, 0.1],
                              [{"face_embed": [0.8, 0.2]},
                               {"face_embed": [0.1, 0.9]}])
    assert g["avg_score"] < 0.65 and not g["passed"]


def test_face_similarity_passes():
    g = face_similarity_gate([0.9, 0.1], [{"face_embed": [0.9, 0.05]}])
    assert g["avg_score"] > 0.9 and g["passed"]


if __name__ == "__main__":
    import pytest
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        try:
            fn()
        except SystemExit:
            raise
        print(f"  PASS {fn.__name__}")
    print(f"共 {len(fns)} 项")
