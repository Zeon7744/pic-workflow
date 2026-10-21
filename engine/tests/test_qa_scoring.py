# -*- coding: utf-8 -*-
"""qa_scoring 单测：4 维打分 + 阈值路由。
运行：PYTHONPATH=src python3 -m pytest tests/test_qa_scoring.py -v
或无 pytest：PYTHONPATH=src python3 tests/test_qa_scoring.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.qa_scoring import ShotMetrics, score_shot, build_requeue

def test_all_pass():
    m = ShotMetrics(consistency_shape=0.95, consistency_style=0.9,
                    continuity_place=0.88, alignment_intent=0.9,
                    duration_s=5.0, expected_duration_s=5.0, keyframe_drift=0.05)
    r = score_shot(m)
    assert r.passed is True, f"应通过: {r.reasons}"
    assert r.route == "pass"

def test_low_shape_redo():
    m = ShotMetrics(consistency_shape=0.60, consistency_style=0.9,
                    continuity_place=0.85, alignment_intent=0.9,
                    duration_s=5.0, expected_duration_s=5.0)
    r = score_shot(m)
    assert r.passed is False
    # 形变低但不算"严重偏移" -> redo_local
    assert r.route == "redo_local", f"got {r.route}"

def test_severe_offset_cloud():
    m = ShotMetrics(consistency_shape=0.9, consistency_style=0.9,
                    continuity_place=0.9, alignment_intent=0.45,
                    duration_s=5.0, expected_duration_s=5.0)
    r = score_shot(m)
    assert r.passed is False
    # 偏移严重(0.45 < 0.82*0.85=0.697) -> cloud_refine
    assert r.route == "cloud_refine", f"got {r.route}"

def test_duration_bad_cloud():
    m = ShotMetrics(consistency_shape=0.9, consistency_style=0.9,
                    continuity_place=0.85, alignment_intent=0.9,
                    duration_s=8.0, expected_duration_s=5.0)  # 超 3s
    r = score_shot(m, duration_tolerance_s=2.0)
    assert r.duration_compliant is False
    assert r.route == "cloud_refine"

def test_keyframe_drift_deducts_shape():
    m1 = ShotMetrics(consistency_shape=0.90, keyframe_drift=0.0)
    m2 = ShotMetrics(consistency_shape=0.90, keyframe_drift=0.5)
    r1, r2 = score_shot(m1), score_shot(m2)
    assert r2.scores["consistency_shape"] < r1.scores["consistency_shape"]

def test_requeue_buckets():
    m_pass = ShotMetrics(shot_id="s1")
    m_redo = ShotMetrics(consistency_shape=0.5, shot_id="s2")
    m_cloud = ShotMetrics(alignment_intent=0.3, shot_id="s3")
    reps = [score_shot(m_pass), score_shot(m_redo), score_shot(m_cloud)]
    q = build_requeue(reps)
    assert "s1" in q["pass"]
    assert "s2" in q["redo_local"]
    assert "s3" in q["cloud_refine"]

if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn()
            ok += 1
            print(f"PASS {fn.__name__}")
        except Exception:
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
