# -*- coding: utf-8 -*-
"""hookforge L0 资产库 + 统一 runner 单测：改角色卡列脏分镜 / 缺失引用报错 / 版本可回溯。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import picwf.hookforge as hf
from picwf.hookforge.runner import RunnerConfig


def _mk(tmp):
    os.makedirs(os.path.join(tmp, "shots", "ep1"), exist_ok=True)
    manifest = {"version": 1, "episodes": {"1": ["shot_ep1_001", "shot_ep1_002"]},
                 "reverse_refs": {"char_X": ["shot_ep1_001", "shot_ep1_002"]}}
    with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    os.makedirs(os.path.join(tmp, "characters"), exist_ok=True)
    with open(os.path.join(tmp, "characters", "char_X.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "char_X", "version": 1, "history": []}, f, ensure_ascii=False)
    for sid in ["shot_ep1_001", "shot_ep1_002"]:
        with open(os.path.join(tmp, "shots", "ep1", sid + ".json"), "w", encoding="utf-8") as f:
            json.dump({"id": sid, "raw": "X", "characters": ["char_X"], "bgm": "bgm_suspense"}, f, ensure_ascii=False)
    return hf.AssetLibrary(root=tmp)


def test_dirty_shots_for_asset(tmpdir=None):
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    lib.bump_version("char_X", "edited")
    assert lib.dirty_shots_for_asset("char_X") == ["shot_ep1_001", "shot_ep1_002"]


def test_missing_asset_raises():
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    try:
        lib.load("bgm_nonexistent")
        raise AssertionError("missing asset should raise")
    except FileNotFoundError:
        pass


def test_version_history_traceable():
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    lib.bump_version("char_X", "edited")
    rec = json.load(open(os.path.join(tmp, "characters", "char_X.json")))
    assert rec["version"] == 2
    assert len(rec["history"]) == 1
    assert rec["history"][0]["action"] == "edited"
    assert rec.get("checksum")


def test_clear_dirty():
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    lib.bump_version("char_X", "e")
    assert "char_X" in lib.manifest.get("dirty", {})
    lib.clear_dirty("char_X")
    assert "char_X" not in lib.manifest.get("dirty", {})


def test_dirty_mode_plan_shots():
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    lib.bump_version("char_X", "e")
    res = hf.run(RunnerConfig(assets_root=tmp, episode=1, mode="dirty", out_dir=os.path.join(tmp, "out")))
    shot_items = [p for p in res.plan if p["kind"] == "shot"]
    assert len(shot_items) >= 2
    assert res.dirty_shots == ["shot_ep1_001", "shot_ep1_002"]


def test_full_mode_plan_has_shots():
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    res = hf.run(RunnerConfig(assets_root=tmp, episode=1, mode="full", out_dir=os.path.join(tmp, "out")))
    kinds = [p["kind"] for p in res.plan]
    assert "shot" in kinds


def test_missing_shot_raises():
    tmp = tempfile.mkdtemp()
    lib = _mk(tmp)
    os.remove(os.path.join(tmp, "shots", "ep1", "shot_ep1_002.json"))
    try:
        hf.run(RunnerConfig(assets_root=tmp, episode=1, mode="full", out_dir=os.path.join(tmp, "out")))
        raise AssertionError("missing shot should raise")
    except FileNotFoundError:
        pass
