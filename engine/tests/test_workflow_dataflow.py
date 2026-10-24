# -*- coding: utf-8 -*-
"""workflow_gen 8 环节全链路数据流编排回归。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from picwf import workflow_gen


def test_8_node_main_chain_present():
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                        style="S1_anime_jp", scenario="dark_thriller",
                                        ep=10, audio_mode="auto")
    ids = [f["id"] for f in wf["dataflow"]]
    for core in ("script_struct", "character_image", "storyboard_prompt",
                 "video_shot", "fx_enhance", "post_assemble",
                 "bgm_audio", "package_publish"):
        assert core in ids, f"主链 {core} 缺失"


def test_upstream_downstream_consistent():
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                        style="S1_anime_jp", scenario="dark_thriller",
                                        ep=10, audio_mode="auto")
    ids = {f["id"] for f in wf["dataflow"]}
    for f in wf["dataflow"]:
        for d in f["depends_on_eff"]:
            assert d in ids, f"{f['id']} 依赖 {d} 不在数据流中"


def test_audio_track_clip_when_absent():
    # 裁剪音频轨（audio_mode=off 或场景无音频）→ 叠加轨不出现
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                        style="S1_anime_jp", scenario="dark_thriller",
                                        ep=10, audio_mode="off")
    ids = [f["id"] for f in wf["dataflow"]]
    assert "music" not in ids or "voice" not in ids
    # 主链仍完整
    assert "post_assemble" in ids and "package_publish" in ids


def test_build_dataflow_returns_list():
    wf = workflow_gen.generate_workflow("T1")
    assert isinstance(wf["dataflow"], list)
    assert len(wf["dataflow"]) >= 8  # 8 主链


def test_dataflow_serializable():
    import yaml
    wf = workflow_gen.generate_workflow("T1")
    text = yaml.safe_dump(wf, allow_unicode=True, sort_keys=False)
    assert "dataflow" in text

def test_mode_overlay_does_not_replace_legacy_workflow_generation():
    wf_default = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                                style="S1_anime_jp",
                                                scenario="dark_thriller",
                                                ep=10, audio_mode="auto")
    wf_pro = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                            style="S1_anime_jp",
                                            scenario="dark_thriller",
                                            ep=10, audio_mode="auto", mode="pro")
    core_keys = ("tier", "style", "nodes", "dataflow", "music", "voice", "bgm")
    for k in core_keys:
        assert wf_default.get(k) == wf_pro.get(k), f"mode overlay changed legacy field {k}"
    assert wf_pro["mode"] == "pro"
    assert wf_pro["mode_overlay"]["legacy_workflow_preserved"] is True
    assert wf_pro["mode_overlay"]["params"].get("resolution") == 720

def test_invalid_mode_falls_back_to_beginner_and_legacy_generation_stays_same():
    wf_bad = workflow_gen.generate_workflow("T1", mode="turbo")
    wf_beginner = workflow_gen.generate_workflow("T1")
    assert wf_bad["mode"] == "beginner"
    assert wf_bad["mode_overlay"]["mode_label"] == "新手"
    assert [f["id"] for f in wf_bad["dataflow"]] == [f["id"] for f in wf_beginner["dataflow"]]

def test_apply_mode_feedback_updates_overlay_without_touching_legacy_fields():
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                       style="S1_anime_jp",
                                       scenario="dark_thriller", ep=10,
                                       audio_mode="auto")
    before_nodes = [dict(n) for n in wf["nodes"]]
    before_flow = [dict(f) for f in wf["dataflow"]]
    fb = {
        "mode": "pro",
        "params_used": {"steps": 32, "resolution": 720},
        "model_id": "wan13b_gguf_q4_offload_480",
        "qa_pass_rate": 0.9,
        "local_models_dir": "D:\ComfyUI\aki\ComfyUI\models\checkpoints",
    }
    wf2 = workflow_gen.apply_mode_feedback(wf, fb)
    assert wf2["mode"] == "pro"
    assert wf2["mode_overlay"]["params"]["steps"] == 32
    assert wf2["mode_feedback_applied"]["applied"] is True
    assert wf2["mode_feedback_applied"]["legacy_fields_preserved"] is True
    assert wf2["nodes"] == before_nodes
    assert wf2["dataflow"] == before_flow

def test_apply_mode_feedback_empty_feedback_is_noop_for_legacy_fields():
    wf = workflow_gen.generate_workflow("T1")
    before = dict(wf)
    wf2 = workflow_gen.apply_mode_feedback(wf, {})
    assert wf2["mode_feedback_applied"]["applied"] is False
    assert wf2["nodes"] == before["nodes"]
    assert wf2["dataflow"] == before["dataflow"]
