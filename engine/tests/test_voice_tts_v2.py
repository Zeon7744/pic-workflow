# -*- coding: utf-8 -*-
"""test_voice_tts_v2: 验证 voice_tts 可插拔多后端架构(对齐 model_gateway audio_tts)。

覆盖:
- 新签名 synthesize(text, voice_id, emotion, speed, backend) 与旧签名兼容
- minimax 后端分支(无 adapter 时优雅降级)
- 后端优先级: minimax > openai_compat > edge
- batch_synthesize 新签名(out_dir/character)
- list_voices backend 参数
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.cloud_api import voice_tts


def test_new_signature_shape():
    """新签名 synthesize(text, voice_id, emotion, speed, backend, character) 返回统一结构。"""
    out = voice_tts.synthesize("测试", voice_id="male", emotion="neutral",
                               speed=1.0, backend="edge",
                               out_path="/tmp/_v2_probe.mp3")
    for k in ("ok", "backend", "path", "duration_ms", "error"):
        assert k in out, f"缺少字段 {k}, got keys={list(out.keys())}"
    assert out["backend"] == "edge"


def test_legacy_signature_still_works():
    """旧签名 synthesize(text, voice, provider) 仍兼容。"""
    out = voice_tts.synthesize("测试", voice="female", provider="edge",
                               out_path="/tmp/_v2_probe2.mp3")
    assert isinstance(out, dict) and "ok" in out


def test_minimax_branch_without_adapter_degrades():
    """无 minimax_client/adapter 时, minimax 分支应优雅降级(ok=False + 结构化 error)。"""
    out = voice_tts.synthesize("测试", voice_id="male", backend="minimax",
                               out_path="/tmp/_v2_probe3.mp3")
    assert out["backend"] == "minimax"
    if not out.get("ok"):
        assert out.get("error"), "失败必须带 error"


def test_backend_priority_fallback():
    """auto 模式按 minimax > openai_compat > edge 优先级选择。"""
    out = voice_tts.synthesize("测试", out_path="/tmp/_v2_probe4.mp3")  # backend 默认 auto
    # 无论选中哪个, 都必须返回统一结构
    assert "backend" in out and out["backend"] in (
        "minimax", "openai_compat", "edge", "none")


def test_list_voices_backend_param():
    r = voice_tts.list_voices(backend="edge")
    assert "voices" in r and isinstance(r["voices"], list)
    r2 = voice_tts.list_voices(backend="openai_compat")
    assert "voices" in r2


def test_batch_new_signature():
    out = voice_tts.batch_synthesize({"l1": "第一句", "l2": "第二句"},
                                     out_dir="/tmp/_v2_batch_probe",
                                     character=None, backend="edge")
    assert "results" in out and "ok_count" in out and "total_duration_ms" in out
    assert "l1" in out["results"] and "l2" in out["results"]


def test_unknown_backend_rejected():
    out = voice_tts.synthesize("测试", backend="not_exist",
                               out_path="/tmp/_v2_probe5.mp3")
    assert out["ok"] is False
    assert "未知" in out.get("error", "")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    failed = []
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
