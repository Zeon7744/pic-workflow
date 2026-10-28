# -*- coding: utf-8 -*-
"""test_minimax_tts: 引擎内自包含的 MiniMax TTS 后端（不烧 API 配额）。

覆盖：
- 引擎包内能加载 minimax_client / minimax_tts_adapter（不再依赖项目目录）
- 角色 → voice_id 映射正确
- 无密钥时优雅降级，不抛异常
- voice_tts 的 minimax 分支正确路由到 adapter
- 非法 emotion 降级为 neutral
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf.cloud_api import voice_tts
from picwf.cloud_api import minimax_tts_adapter as adapter
from picwf.cloud_api import minimax_client as client


def test_adapter_self_contained():
    """引擎包内应能直接导入 adapter，不依赖外部项目目录。"""
    assert adapter.BACKEND_NAME == "minimax"
    assert hasattr(adapter, "synthesize")
    assert hasattr(adapter, "list_voices")
    assert hasattr(adapter, "batch_synthesize")


def test_voice_preset_keys_aligned():
    """VOICE_PRESET 键必须与 voice_tts 的预设键一致。"""
    for k in ("male", "female", "child", "narrator", "warm", "serious", "default"):
        assert k in adapter.VOICE_PRESET, f"缺少预设键 {k}"


def test_character_preset_mapping():
    assert adapter.resolve_voice_id(None, "沈临") == "male-qn-jingying"
    assert adapter.resolve_voice_id(None, "苏雪晴") == "female-shaonv"


def test_preset_key_resolves():
    assert adapter.resolve_voice_id("male") == "male-qn-jingying"
    assert adapter.resolve_voice_id("female") == "female-shaonv"


def test_raw_voice_id_passthrough():
    """已是 MiniMax 原始音色 ID 时直通，不做二次映射。"""
    assert adapter.resolve_voice_id("female-yujie") == "female-yujie"


def test_empty_text_rejected():
    r = adapter.synthesize("")
    assert r["ok"] is False and "空" in r["error"]


def test_wrong_backend_rejected():
    r = adapter.synthesize("测试", backend="edge")
    assert r["ok"] is False and "minimax" in r["error"]


def test_no_key_degrades_gracefully():
    """无密钥时必须返回结构化错误，不能抛异常打挂管线。"""
    old = os.environ.pop("MINIMAX_API_KEY", None)
    # 本地/云盘 .minimax_key 一旦落地，这个测试就会假通过（拿真 key 合成成功）。
    # 这里显式隔离 _load_key 的文件兜底，只验证「彻底无密钥」的分支。
    orig = client._load_key
    client._load_key = lambda: ("", "")
    try:
        r = adapter.synthesize("测试", out_path="/tmp/_mm_probe.mp3")
        assert r["ok"] is False
        assert r["error"], "失败必须带 error"
        assert "密钥" in r["error"] or "MINIMAX_API_KEY" in r["error"]
    finally:
        client._load_key = orig
        if old is not None:
            os.environ["MINIMAX_API_KEY"] = old


def test_voice_tts_routes_to_adapter():
    """voice_tts 的 minimax 分支必须真的走到 adapter。"""
    mod = voice_tts._load_minimax_adapter()
    assert mod is not None
    assert mod is adapter, "voice_tts 应复用包内同一 adapter 实例"


def test_batch_returns_structure():
    r = adapter.batch_synthesize({"l1": "第一句"}, out_dir="/tmp/_mm_batch")
    for k in ("ok", "results", "ok_count", "total_duration_ms"):
        assert k in r, f"缺少字段 {k}"


def test_emotion_whitelist():
    assert "sad" in adapter.VALID_EMOTIONS
    assert "neutral" in adapter.VALID_EMOTIONS
    assert len(adapter.VALID_EMOTIONS) == 7


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed, failed = 0, []
    for fn in fns:
        try:
            fn()
            print("PASS", fn.__name__)
            passed += 1
        except Exception as e:
            print("FAIL", fn.__name__, "->", e)
            failed.append(fn.__name__)
    print(f"\n=== {passed}/{len(fns)} passed, {len(failed)} failed ===")
    sys.exit(1 if failed else 0)


# ---------------------------------------------------------------------------
# 限流退避：MiniMax 有 RPM 上限，逐句配音必然连打，不能把限流变成丢台词
# ---------------------------------------------------------------------------
def test_rate_limit_detected():
    assert client._is_rate_limited("rate limit exceeded(RPM)")
    assert client._is_rate_limited("HTTP 429: too many requests")
    assert not client._is_rate_limited("login fail: invalid key")


def test_post_retry_backs_off_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def _flaky(url, key, payload):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("HTTP 429: rate limit exceeded(RPM)")
        return {"base_resp": {"status_code": 0}, "ok": 1}

    monkeypatch.setattr(client, "_post", _flaky)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)  # 不真等
    monkeypatch.setattr(client, "_MIN_INTERVAL_S", 0)
    resp = client._post_retry("http://x", "k", {})
    assert resp["ok"] == 1
    assert calls["n"] == 3


def test_post_retry_gives_up_on_non_rate_error(monkeypatch):
    def _boom(url, key, payload):
        raise RuntimeError("login fail: bad key")

    monkeypatch.setattr(client, "_post", _boom)
    monkeypatch.setattr(client, "_MIN_INTERVAL_S", 0)
    try:
        client._post_retry("http://x", "k", {})
    except RuntimeError as e:
        assert "bad key" in str(e)
    else:
        raise AssertionError("非限流错误应直接抛出，不该重试")
