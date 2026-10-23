# -*- coding: utf-8 -*-
"""assembler ffmpeg 真合成回归。"""
import sys
import os
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from picwf import assembler


@pytest.mark.skipif(not assembler.ffmpeg_available(), reason="ffmpeg 不可用")
def test_assemble_placeholder_clips(tmp_path):
    out = assembler.assemble(["", "", ""],
                             out_path=str(tmp_path / "final.mp4"),
                             workdir=str(tmp_path))
    assert out["ok"] is True
    assert out["clip_count"] == 3
    assert out["duration_s"] > 0
    assert os.path.exists(out["out"]) and os.path.getsize(out["out"]) > 0
    # 真可播放：ffprobe 验证
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "csv=p=0", out["out"]], capture_output=True)
    assert float(r.stdout.decode().strip()) > 0


@pytest.mark.skipif(not assembler.ffmpeg_available(), reason="ffmpeg 不可用")
def test_assemble_with_audio(tmp_path):
    audio = str(tmp_path / "bgm.wav")
    assembler._gen_placeholder_audio(audio, freq=440, duration_s=4.0)
    out = assembler.assemble(["", ""], audio_tracks=[audio],
                             out_path=str(tmp_path / "f.mp4"),
                             workdir=str(tmp_path))
    assert out["audio_tracks"] == 1
    assert out["ok"] is True


def test_assemble_no_ffmpeg_degrades(tmp_path, monkeypatch):
    monkeypatch.setattr(assembler, "ffmpeg_available", lambda: False)
    out = assembler.assemble(["", ""], out_path=str(tmp_path / "f.mp4"),
                             workdir=str(tmp_path))
    assert out["ok"] is False
    assert out["ffmpeg"] is False
    assert out["mode"] == "placeholder_no_ffmpeg"


def test_full_pipeline_ffmpeg_assembled(tmp_path):
    from picwf import workflow_gen, pipeline_runner as pr
    from picwf import pipeline_executors as pe
    if not assembler.ffmpeg_available():
        pytest.skip("ffmpeg 不可用")
    wf = workflow_gen.generate_workflow("T1", free_vram_gb=6.0,
                                        style="S1_anime_jp",
                                        scenario="dark_thriller", ep=10,
                                        audio_mode="auto")
    wf["episode"] = 10
    ex = pe.make_executors(wf, workdir=str(tmp_path))
    res = pr.run_pipeline_8stage(wf, ex,
                                 upstream_inputs={"script_struct": {"text": "第1场：男主进屋"}})
    pp = res["artifacts"]["package_publish"]
    assert pp["publish_ready"] is True
    assert pp["duration_s"] > 0
    assert os.path.exists(pp["final_video"])
