# -*- coding: utf-8 -*-
"""agnes 图像接入 + 分镜出场角色判定。"""
import pytest

from picwf.cloud_api import agnes_image as ai
from picwf.pipeline_executors import _on_screen_chars, _char_anchor

CHARS = {
    "林夏": {"age": 27, "gender": "female", "desc": "黑色中分微卷"},
    "周总": {"age": 45, "gender": "male", "desc": "西装油头"},
    "陈姐": {"age": 35, "gender": "female", "desc": "朴素干练"},
}


def test_busy_detects_read_timeout():
    # 出图超时是常态，必须当可重试而不是硬失败
    assert ai._is_busy("The read operation timed out") is True
    assert ai._is_busy("queue_full") is True
    assert ai._is_busy("insufficient_user_quota") is False


def test_run_image_passes_ref_to_i2i(monkeypatch):
    seen = {}

    def fake_post(path, body, timeout=30):
        seen.update(body)
        return {"data": [{"url": "https://x/y.png"}]}

    monkeypatch.setattr(ai, "has_key", lambda s: True)
    monkeypatch.setattr(ai, "_post", fake_post)
    monkeypatch.setattr(ai, "download",
                        lambda url, out="": {"ok": True, "path": out, "bytes": 1})
    r = ai.run_image("p", out_path="/tmp/_z.png", ref_image="https://ref/1.png")
    assert r["ok"] is True
    assert seen["image"] == "https://ref/1.png"


def test_run_image_accepts_ref_list(monkeypatch):
    seen = {}

    def fake_post(path, body, timeout=30):
        seen.update(body)
        return {"data": [{"url": "https://x/y.png"}]}

    monkeypatch.setattr(ai, "has_key", lambda s: True)
    monkeypatch.setattr(ai, "_post", fake_post)
    monkeypatch.setattr(ai, "download",
                        lambda url, out="": {"ok": True, "path": out, "bytes": 1})
    ai.run_image("p", out_path="/tmp/_z.png", ref_image=["a", "b"])
    assert seen["image"] == ["a", "b"]


def test_run_image_omits_ref_when_absent(monkeypatch):
    seen = {}

    def fake_post(path, body, timeout=30):
        seen.update(body)
        return {"data": [{"url": "https://x/y.png"}]}

    monkeypatch.setattr(ai, "has_key", lambda s: True)
    monkeypatch.setattr(ai, "_post", fake_post)
    monkeypatch.setattr(ai, "download",
                        lambda url, out="": {"ok": True, "path": out, "bytes": 1})
    ai.run_image("p", out_path="/tmp/_z.png")
    assert "image" not in seen


def test_run_image_empty_prompt_rejected():
    assert ai.run_image("  ")["ok"] is False


def test_on_screen_ignores_mentioned_names():
    # 关键：台词里被点名的角色没在画面里，不能把定妆照塞进 i2i
    assert _on_screen_chars("陈姐：还不去？周总要的是坑你。", CHARS) == ["陈姐"]


def test_on_screen_handles_hint_before_colon():
    assert _on_screen_chars("林夏（面无表情）：但我没做过这类项目。", CHARS) == ["林夏"]


def test_on_screen_narration_ordered_by_position():
    got = _on_screen_chars("周总将一份文件甩到林夏桌上。", CHARS)
    assert got == ["周总", "林夏"]


def test_on_screen_single_narration():
    assert _on_screen_chars("陈姐路过，停步。", CHARS) == ["陈姐"]


def test_on_screen_no_character():
    assert _on_screen_chars("窗外下起了雨。", CHARS) == []


def test_char_anchor_includes_age_gender_desc():
    a = _char_anchor("周总", CHARS)
    assert "周总" in a and "45岁" in a and "男性" in a and "西装油头" in a


def test_char_anchor_empty_for_absent():
    assert _char_anchor("林夏", None) == ""
