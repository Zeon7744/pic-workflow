# -*- coding: utf-8 -*-
"""pipeline_executors 8 环节真执行器全链回归。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from picwf import workflow_gen, pipeline_runner as pr
from picwf import pipeline_executors as pe


def _run_full(script, ep=10, tmp_path=None):
    import tempfile, os
    wd = str(tmp_path) if tmp_path else tempfile.mkdtemp()
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0, style="S1_anime_jp",
                                        scenario="dark_thriller", ep=ep,
                                        audio_mode="auto")
    wf["episode"] = ep
    ex = pe.make_executors(wf, workdir=wd)
    return wf, pr.run_pipeline_8stage(wf, ex,
                                       upstream_inputs={"script_struct": {"text": script}})


def test_full_chain_publish_ready():
    _, res = _run_full("第1场：男主进屋看到刀\n第2场：男主拿起刀冲门")
    assert res["ok"]
    assert res["artifacts"]["package_publish"]["publish_ready"] is True


def test_video_clips_populated():
    _, res = _run_full("第1场：男主进屋\n第2场：对峙\n第3场：反杀")
    clips = res["artifacts"]["video_shot"]["video_clips"]
    assert len(clips) >= 3


def test_bgm_track_advised():
    _, res = _run_full("第1场：男主进屋")
    assert res["artifacts"]["bgm_audio"]["bgm_track"]


def test_video_shot_feeds_mode_feedback_back_into_workflow_asset():
    import importlib
    pe = importlib.reload(importlib.import_module("picwf.pipeline_executors"))
    wf = {"tier": "T1", "style": "S2_real_cinematic", "scenario": "dark_thriller",
          "episode": 1, "free_vram_gb": 8, "mode": "pro",
          "local_models": ["wan13b_gguf_q4_offload_480.safetensors"],
          "local_models_dir": "D:\ComfyUI\aki\ComfyUI\models\checkpoints"}
    ex = pe.make_executors(wf, workdir="/tmp/pe_mode_feedback_test")
    up = {"storyboard_prompt": {"shots": [{"index": 1, "prompt": "雨夜巷尾"}]}}
    out = ex["video_shot"](up)
    assert out["accessibility"]["mode_feedback"]["can_feedback_to_original_workflow"] is True
    assert out["accessibility"]["mode_feedback"]["mode"] == "pro"
    assert wf["mode"] == "pro"
    assert wf["mode_overlay"]["iteration_feedback"][-1]["model_id"] == out["accessibility"]["mode_feedback"]["model_id"]
    assert wf["mode_feedback_applied"]["applied"] is True


def test_post_assemble_aggregates():
    _, res = _run_full("第1场：男主进屋\n第2场：对峙")
    pa = res["artifacts"]["post_assemble"]
    assert pa["clip_count"] >= 2
    assert pa["assembled_video"]


def test_resume_pipeline():
    import tempfile
    wd = tempfile.mkdtemp()
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0, style="S1_anime_jp",
                                        scenario="dark_thriller", ep=5, audio_mode="auto")
    wf["episode"] = 5
    ex = pe.make_executors(wf, workdir=wd)
    res = pr.run_pipeline_8stage(wf, ex,
                                  upstream_inputs={"script_struct": {"text": "x"}},
                                  resume_ids=["script_struct", "character_image"])
    assert "script_struct" in res["skipped"]
    assert res["artifacts"]["script_struct"].get("_resumed") is True
