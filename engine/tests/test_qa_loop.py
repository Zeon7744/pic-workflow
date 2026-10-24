# -*- coding: utf-8 -*-
"""qa_loop 行为测试。

运行：python engine/tests/test_qa_loop.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf.qa_loop import decide_qa_loop, summarize_qa_loop


def _plan():
    return {
        "kind": "video",
        "paths": [
            {"path_id": "p1", "model_id": "wan13b_gguf_q4_offload_480",
             "cloud": False, "score": 0.80, "resource_ok": True},
            {"path_id": "p2", "model_id": "cloud_seedance_2",
             "cloud": True, "score": 0.92, "resource_ok": True},
            {"path_id": "p3", "model_id": "cloud_kling",
             "cloud": True, "score": 0.88, "resource_ok": True},
        ],
        "best": {"model_id": "wan13b_gguf_q4_offload_480"},
        "gate": {"has_path": True, "best_path": "p1"},
    }


def test_decide_pass_is_accepted():
    report = {"passed": True, "route": "pass",
              "scores": {"alignment_intent": 0.9}}
    out = decide_qa_loop(report, plan=_plan(), current_model="wan13b_gguf_q4_offload_480",
                         attempt=0)
    assert out["action"] == "accepted"
    assert out["model"] == "wan13b_gguf_q4_offload_480"


def test_decide_redo_local_can_switch_candidate():
    report = {"passed": False, "route": "redo_local",
              "scores": {"alignment_intent": 0.75}}
    out = decide_qa_loop(report, plan=_plan(),
                         current_model="wan13b_gguf_q4_offload_480", attempt=0)
    assert out["action"] in {"retry_candidate", "degrade_params"}
    assert out["attempt"] == 1


def test_decide_cloud_refine_escalates_when_allowed():
    report = {"passed": False, "route": "cloud_refine",
              "scores": {"alignment_intent": 0.65}}
    out = decide_qa_loop(report, plan=_plan(), current_model="wan13b_gguf_q4_offload_480",
                         attempt=0, policy={"escalate_to_cloud": True})
    assert out["action"] == "escalate_cloud"
    assert out["cloud"] is True
    assert out["model"] in {"cloud_seedance_2", "cloud_kling"}


def test_decide_retry_exhaustion_marks_failed():
    report = {"passed": False, "route": "redo_local",
              "scores": {"alignment_intent": 0.6}}
    out = decide_qa_loop(report, plan=_plan(), current_model="wan13b_gguf_q4_offload_480",
                         attempt=5, policy={"max_retries": 2})
    assert out["action"] == "failed"


def test_summarize_shape_is_exportable():
    decisions = [
        {"action": "accepted"},
        {"action": "retry_candidate"},
        {"action": "escalate_cloud"},
        {"action": "failed"},
    ]
    summary = summarize_qa_loop(decisions)
    assert summary["total"] == 4
    assert summary["accepted"] == 1
    assert summary["escalated"] == 1
    assert summary["has_failure"] is True
    assert 0.0 <= summary["pass_rate"] <= 1.0


def test_pipeline_executors_video_shot_exposes_qa_loop_summary():
    """video_shot 已在执行链路上暴露 qa_loop_summary，证明质量闭环已接入。"""
    import importlib
    pe = importlib.reload(importlib.import_module("picwf.pipeline_executors"))
    wf = {"tier": "T1", "style": "S2_real_cinematic", "scenario": "dark_thriller",
          "episode": 1, "free_vram_gb": 8, "characters": [
              {"name": "叶轻", "role": "主角", "gender": "女性"}]}
    ex = pe.make_executors(wf, workdir="/tmp/pe_qa_test")
    up = {"storyboard_prompt": {"shots": [{"index": 1, "prompt": "雨夜巷尾"}]},
          "script_struct": {"shots": [{"index": 1, "prompt": "雨夜巷尾"}]}}
    out = ex["video_shot"](up)
    assert "qa_loop_summary" in out
    assert out["qa_loop_summary"]["total"] >= 0
    assert "pass_rate" in out["qa_loop_summary"]


if __name__ == "__main__":
    for name in ("test_decide_pass_is_accepted",
                 "test_decide_redo_local_can_switch_candidate",
                 "test_decide_cloud_refine_escalates_when_allowed",
                 "test_decide_retry_exhaustion_marks_failed",
                 "test_summarize_shape_is_exportable",
                 "test_pipeline_executors_video_shot_exposes_qa_loop_summary"):
        globals()[name]()
        print(f"PASS {name}")
