# -*- coding: utf-8 -*-
"""agnes 视频接入管线：路径/时长/非 mock 标记必须正确传下去。"""
import os

import pytest


def test_video_shot_uses_agnes_path(monkeypatch, tmp_path):
    """agnes 返回本地文件后，video_shot 必须把 path 传下去且标 mock=False。

    否则又会退回「画面是占位片却报成功」的老问题。
    """
    from picwf import pipeline_executors as pe
    from picwf.cloud_api import agnes_video as av

    fake = str(tmp_path / "clip.mp4")
    with open(fake, "wb") as f:
        f.write(b"\x00" * 2048)

    def _fake_run_shot(prompt, **kw):
        return {"ok": True, "path": fake, "video_url": "http://x/v.mp4",
                "model": av.MODEL_FLASH, "backend": "agnes_video"}

    monkeypatch.setattr(av, "run_shot", _fake_run_shot)
    monkeypatch.setattr(pe, "has_key", lambda svc: True, raising=False)

    wf = {"cloud_model_override": "agnes"}
    executors = pe.make_executors(wf, workdir=str(tmp_path))
    up = {
        "storyboard_prompt": {"shots": [
            {"index": 1, "prompt": "中景，办公室", "est_s": 5.4},
        ]},
        "script_struct": {"shots": [{"index": 1, "raw": "x", "est_s": 5.4}]},
    }
    res = executors["video_shot"](up)
    clips = res.get("video_clips") or []
    assert clips, "应该产出镜头结果"
    c0 = clips[0]
    assert c0.get("path") == fake, f"必须带真实本地路径，实得 {c0.get('path')!r}"
    assert c0.get("mock") is False, "agnes 真生成不能标 mock"
    assert abs(float(c0.get("est_s")) - 5.4) < 0.01, "est_s 要传给合成环节对齐时长"
