# -*- coding: utf-8 -*-
"""pipeline_runner 8 环节 dataflow 拓扑执行 + 剧本解析回归。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from picwf import pipeline_runner as pr
from picwf import workflow_gen


def _wf():
    return workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                          style="S1_anime_jp",
                                          scenario="dark_thriller",
                                          ep=10, audio_mode="auto")


def test_topo_order_no_cycle():
    order = pr.topo_order(_wf()["dataflow"])
    assert len(order) == len(_wf()["dataflow"])
    # 上游必在下游前
    for f in _wf()["dataflow"]:
        for d in f.get("depends_on_eff", []):
            if d in order:
                assert order.index(d) < order.index(f["id"])


def test_topo_cycle_raises():
    bad = [
        {"id": "a", "stage": 1, "inputs": [], "outputs": [], "depends_on_eff": ["b"]},
        {"id": "b", "stage": 1, "inputs": [], "outputs": [], "depends_on_eff": ["a"]},
    ]
    with pytest.raises(pr.TopologyError):
        pr.topo_order(bad)


def test_run_8stage_full():
    wf = _wf()
    # 简单执行器：每环节返回 consumed 列表
    ex = {f["id"]: (lambda up, _id=f["id"]: {"ok": True, "stage": _id,
                                               "consumed": list(up.keys())})
          for f in wf["dataflow"]}
    ex["script_struct"] = lambda up: {"ok": True, "stage": "script_struct",
                                       "shots": up.get("script_struct", {}).get("shots", [])}
    res = pr.run_pipeline_8stage(wf, ex,
                                  upstream_inputs={"script_struct": {"shots": ["s1", "s2"]}})
    assert res["ok"] is True
    assert "script_struct" in res["artifacts"]
    assert "package_publish" in res["artifacts"]
    # 下游消费了上游
    assert len(res["artifacts"]["package_publish"]["consumed"]) >= 1


def test_resume_skips_done():
    wf = _wf()
    ex = {f["id"]: (lambda up, _id=f["id"]: {"ok": True, "stage": _id})
          for f in wf["dataflow"]}
    res = pr.run_pipeline_8stage(wf, ex, resume_ids=["script_struct", "character_image"])
    assert "script_struct" in res["skipped"]
    assert res["artifacts"]["script_struct"].get("_resumed") is True


def test_script_to_shots():
    script = "第1场：男主进屋\n第2场：男主看到刀\n第3场：男主拿起刀"
    out = pr.script_to_shots(script, shots_per_ep=10)
    assert out["shot_count"] == 10
    assert out["shots"][0]["raw"] == "第1场：男主进屋"
    assert len(out["shots"]) == 10


def test_wire_orchestrator_stage():
    wf = _wf()
    ex = pr.wire_orchestrator_stage(wf, orchestrator_runner=lambda **k: {
        "executed": ["shot_1"], "remaining_failed": []})
    assert "video_shot" in ex
    # 跑 video_shot 执行器
    out = ex["video_shot"]({})
    assert "video_clips" in out


def test_full_pipeline_with_orchestrator_wire():
    wf = _wf()
    ex = pr.wire_orchestrator_stage(wf, orchestrator_runner=lambda **k: {
        "executed": ["shot_1", "shot_2"], "remaining_failed": []})
    res = pr.run_pipeline_8stage(wf, ex,
                                 upstream_inputs={"script_struct": {"shots": ["a", "b"]}})
    assert "video_shot" in res["artifacts"]
    assert res["artifacts"]["video_shot"]["video_clips"] == ["shot_1", "shot_2"]
