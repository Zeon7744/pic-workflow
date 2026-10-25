# -*- coding: utf-8 -*-
"""i18n bilingual tests."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import picwf.i18n as i18n

def test_set_locale_and_t():
    i18n.set_locale("zh")
    assert i18n.get_locale() == "zh"
    assert i18n.t("brand") != "HookForge"
    i18n.set_locale("en")
    assert i18n.t("brand") == "HookForge"

def test_unknown_key_returns_key():
    i18n.set_locale("zh")
    assert i18n.t("no_such_key_999") == "no_such_key_999"

def test_style_options_bidi():
    i18n.set_locale("en")
    assert i18n.style_options()[0] == ("S1_anime_jp", "JP Anime")
    i18n.set_locale("zh")
    assert len(i18n.style_options()) == 20

def test_scenario_options_bidi():
    i18n.set_locale("en")
    assert i18n.scenario_options()[0][1] == "Light Comedy"

def test_tier_options_bidi():
    i18n.set_locale("en")
    en = i18n.tier_options()
    assert len(en) == 3
    assert "no dGPU" in en[0][1]

def test_l10n_js_valid():
    i18n.set_locale("en")
    parsed = json.loads(i18n.l10n_js())
    assert len(parsed["stages"]) == 9
    i18n.set_locale("zh")
    parsed_zh = json.loads(i18n.l10n_js())
    assert parsed_zh["stages"]["video_shot"] != parsed["stages"]["video_shot"]

def test_all_ui_text_keys():
    i18n.set_locale("en")
    txt = i18n.all_ui_text()
    for k in ("brand","hero_title","card_script","btn_run","stage_video_shot"):
        assert k in txt, k
