# -*- coding: utf-8 -*-
"""test_comic_and_tts: 漫剧工作流互通 + 自有 TTS 能力测试。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import comic_drama_workflow as cdw
from picwf.cloud_api import voice_tts


# ---------------------------------------------------------- 漫剧工作流
def test_list_templates_has_three_core():
    tpl = cdw.list_available_templates()
    for name in ("character_sheet", "storyboard", "motion"):
        assert name in tpl, f"缺少核心漫剧工作流模板 {name}, got {tpl}"


def test_get_registry_shapes():
    reg = cdw.get_registry()
    assert "character_sheet" in reg
    cs = reg["character_sheet"]
    assert cs.get("outputs"), "character_sheet 应声明 outputs"
    assert "tier_compat" in cs


def test_render_character_sheet_replaces_placeholders():
    r = cdw.render_workflow(
        "character_sheet",
        overrides={"character_prompt": "a cyberpunk android girl, red eyes", "variant": 2},
        tier="T3")
    texts = [n["inputs"].get("text") for n in r["workflow"].values()
             if n["class_type"] == "CLIPTextEncode"]
    assert any("cyberpunk android girl" in (t or "") for t in texts)
    assert not cdw.validate_rendered(r["workflow"]), cdw.validate_rendered(r["workflow"])


def test_render_low_tier_warns():
    r = cdw.render_workflow("storyboard", tier="T0")
    assert r["warnings"], f"低档渲染 storyboard 应有档位告警, got {r['warnings']}"


def test_render_good_tier_no_warning():
    r = cdw.render_workflow("motion", tier="T4")
    tier_warns = [w for w in r["warnings"] if "档位" in w]
    assert not tier_warns, f"T4 渲染 motion 不应有档位告警: {tier_warns}"


def test_validate_catches_unreplaced_placeholder():
    bad = {"1": {"class_type": "KSampler",
                 "inputs": {"latent": ["9", 0], "seed": "{{seed}}"}}}
    issues = cdw.validate_rendered(bad)
    assert any("占位符" in i for i in issues)
    assert any("9" in i for i in issues)


def test_unknown_template_raises():
    try:
        cdw.load_template("not_exist")
        assert False, "应抛 FileNotFoundError"
    except FileNotFoundError:
        pass


# ---------------------------------------------------------- 自有 TTS
def test_voice_preset_keys():
    for k in ("male", "female", "child", "narrator", "default"):
        v = voice_tts._resolve_voice(k)
        assert "Neural" in v, f"{k} 应映射到 edge 音色, got {v}"


def test_auto_provider_graceful_without_backend():
    out = voice_tts.synthesize("你好世界", provider="auto",
                               out_path="/tmp/_tts_probe.mp3")
    assert isinstance(out, dict) and "ok" in out and "provider" in out and "error" in out
    if not out.get("ok"):
        assert out.get("error"), "失败应带 error 信息"


def test_list_voices_shape():
    r = voice_tts.list_voices("edge")
    assert "voices" in r and isinstance(r["voices"], list)
    r2 = voice_tts.list_voices("openai_compat")
    assert "voices" in r2


def test_batch_shape():
    out = voice_tts.batch_synthesize({"l1": "第一句", "l2": "第二句"},
                                     tmp_dir="/tmp/_tts_batch_probe")
    assert "results" in out and "ok" in out
    assert "l1" in out["results"] and "l2" in out["results"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print("PASS", fn.__name__)
        passed += 1
    print(f"\n=== {passed}/{len(fns)} passed ===")
