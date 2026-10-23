# -*- coding: utf-8 -*-
"""Web UI Flask 端点回归（test client，不依赖常驻服务）。"""
import sys, os
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "ui"))

import app as uiapp


def _client():
    return uiapp.app.test_client()


def test_index_200():
    r = _client().get("/")
    assert r.status_code == 200
    b = r.data.decode()
    assert "爽点厂" in b
    assert "一键出片" in b


def test_options_api():
    r = _client().get("/api/options")
    d = r.get_json()
    assert len(d["styles"]) == 20
    assert len(d["scenarios"]) == 10
    assert len(d["tiers"]) == 3


def test_run_empty_script_rejected():
    r = _client().post("/api/run", json={"script": "  "})
    assert r.status_code == 400
    assert "剧本不能为空" in r.get_json()["error"]


def test_run_full_pipeline():
    r = _client().post("/api/run", json={
        "script": "第1场：男主进屋\n第2场：反转真相",
        "tier": "T1", "style": "S1_anime_jp",
        "scenario": "dark_thriller", "ep": 5,
        "free_vram_gb": 6, "audio_mode": "auto"})
    d = r.get_json()
    assert d["ok"] is True
    assert d["video_download"] is True
    assert len(d["completed"]) == len(d["order"])
    assert d["final_video"]


def test_download_safe_path_only(tmp_path):
    # 合法 /tmp/hookforge_ui_* 路径
    td = tmp_path if str(tmp_path).startswith("/tmp") else Path("/tmp") / "hookforge_ui_test_dl"
    import tempfile
    if not td.name.startswith("hookforge_ui"):
        td = Path(tempfile.mkdtemp(prefix="hookforge_ui_"))
    vid = td / "out" / "final.mp4"
    vid.parent.mkdir(parents=True, exist_ok=True)
    vid.write_bytes(b"mp4")
    r = _client().get(f"/download/{vid.as_posix().lstrip('/')}")
    assert r.status_code == 200
    # 越权路径必须拒
    r2 = _client().get("/download/etc/passwd")
    assert r2.status_code == 400
