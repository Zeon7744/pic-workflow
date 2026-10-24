# -*- coding: utf-8 -*-
"""prompt_craft + character_consistency + topic_adapt 单测。

覆盖白皇 6 要求：人性化 / 智能化 / 覆盖面广 / 生成不偏移 / 精确 / 不走样。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.character_consistency import (
    build_character_block, build_three_view_prompt, inject_into_shots,
    three_view_anchor_refs)
from picwf.prompt_craft import build_shot_prompt, craft_all_shots
from picwf.topic_adapt import detect_topic, adapt_script, adapt_shot_style


# --- 角色一致性（不走样）---
def test_char_block_locks_appearance():
    c = build_character_block({"name": "林晚", "gender": "女性"})
    assert "林晚" in c and "保持一致" in c and "consistent" in c  # 中英双版本


def test_char_block_injection_by_dialogue():
    chars = [{"name": "林晚"}, {"name": "男主"}]
    shots = [{"index": 1, "raw": "林晚推门", "prompt": "p"},
             {"index": 2, "raw": "男主冷笑", "prompt": "p"}]
    out = inject_into_shots(shots, chars)
    assert out[0]["present_chars"] == ["林晚"]
    assert out[1]["present_chars"] == ["男主"]
    assert "角色基准" in out[0]["prompt"]


def test_char_injection_default_hero_fallback():
    chars = [{"name": "林晚"}]
    out = inject_into_shots([{"index": 1, "raw": "推门", "prompt": "p"}], chars)
    assert out[0]["present_chars"] == ["林晚"]  # 台词没提也锚定第一主角


def test_three_view_refs_paths():
    refs = three_view_anchor_refs([{"name": "林晚"}], "/wd")
    assert refs[0]["three_view_path"].endswith("林晚_3view.png")
    assert "three views" in refs[0]["prompt"]


# --- prompt_craft（精确 + 人性化）---
def test_shot_prompt_six_dims():
    p = build_shot_prompt({"shot_type": "特写", "motion": "急推",
                           "emotion": "爆发", "raw": "摔文件"})
    assert "机位" in p and "构图" in p and "光位" in p and "色调" in p
    assert "情绪爆发" in p  # 人性化情绪层


def test_shot_prompt_no_deform_tail():
    p = build_shot_prompt({"emotion": "沉淀", "raw": "x"})
    assert "不走形" in p or "不走样" in p


# --- topic_adapt（覆盖面广 + 智能化）---
def test_detect_topic_ancient():
    assert detect_topic("太子与王妃在殿内对坐") == "古装"


def test_detect_topic_scifi():
    assert detect_topic("2199 年太空站，机甲 AI") == "科幻"


def test_detect_topic_fallback_real():
    assert detect_topic("咖啡馆聊琐事") == "现实"


def test_topic_style_switch():
    s_anc = adapt_shot_style("古装", {})
    s_sci = adapt_shot_style("科幻", {})
    assert s_anc["palette"] != s_sci["palette"]  # 题材切不同色调


def test_adapt_script_end_to_end():
    res = adapt_script("太子殿内", [{"index": 1, "shot_type": "中景",
                                     "emotion": "反转", "raw": "递茶"}],
                       chars=[{"name": "太子"}])
    assert res["topic"] == "古装"
    assert "角色基准" in res["shots"][0]["final_prompt"]
    assert res["style"]["palette"] == "水墨暖调"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn(); passed += 1
        print(f"  PASS {fn.__name__}")
    print(f"共 {passed} 项通过")
