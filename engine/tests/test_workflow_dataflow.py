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
