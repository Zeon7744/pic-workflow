# -*- coding: utf-8 -*-
"""B 块（专业分镜拆解）+ C 块（CLI 端到端出片）回归。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from picwf.pipeline_runner import script_to_shots
from picwf import pipeline_cli


def test_script_to_shots_professional_prompt():
    out = script_to_shots("第1场：男主进屋看到刀\n第2场：反转真相", shots_per_ep=10)
    assert out["mode"] in ("rules", "llm")
    # 每镜头有专业 prompt（景别+运动+情绪）
    for s in out["shots"]:
        assert s["prompt"], "prompt 不应为空"
        assert s["shot_type"] in ("特写", "近景", "中景", "全景")
    # 反转命中
    assert any(s["emotion"] == "反转" for s in out["shots"][:2])


def test_script_to_shots_skip_md_header():
    out = script_to_shots("# 江城情缘\n第1场：男主进屋\n第2场：对峙", shots_per_ep=10)
    # markdown 标题 # 开头的不进 shots
    assert not any(s["raw"].startswith("#") for s in out["shots"])
    assert out["shots"][0]["raw"].startswith("第1场")


def test_script_to_shots_llm_mode():
    llm = [{"text": "男主进屋", "prompt": "特写（缓推）男主进屋"}]
    out = script_to_shots("x", shots_per_ep=10, use_llm=True, llm_fn=lambda t: llm)
    assert out["mode"] == "llm"
    assert out["shots"][0]["prompt"] == "特写（缓推）男主进屋"


def test_cli_end_to_end(tmp_path):
    script = tmp_path / "script.md"
    script.write_text("# 江城情缘\n第1场：男主进屋\n第2场：反转真相", encoding="utf-8")
    out_dir = tmp_path / "out"
    res = pipeline_cli.run(str(script), tier="T1", scenario="dark_thriller",
                          ep=5, workdir=str(out_dir))
    assert res["ok"] is True
    assert res["final_video"], "成片路径不应为空"
    assert res["report"]
    # 报告已落盘
    import json
    r = json.load(open(res["report"]))
    assert r["artifacts"]["package_publish"]["publish_ready"] is True
    assert len(r["completed"]) == len(r["order"])


def test_cli_resume(tmp_path):
    script = tmp_path / "script.md"
    script.write_text("第1场：男主进屋\n第2场：对峙", encoding="utf-8")
    out_dir = tmp_path / "out2"
    res = pipeline_cli.run(str(script), tier="T1", ep=5,
                           workdir=str(out_dir),
                           resume_ids=["script_struct", "character_image"])
    assert "script_struct" in res["skipped"]
    assert res["ok"] is True
