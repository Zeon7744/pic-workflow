# -*- coding: utf-8 -*-
"""i18n：中英双语支持层。

提供：
- L10N dict 存 zh/en 两套文案
- t(key) 按当前 locale 取文案
- set_locale("zh"|"en") 切换
- 所有 UI 下拉选项/标题/提示的中英对照

设计：
- 默认 zh（白皇受众），切 en 后所有文案英文化
- 不依赖外部 gettext/babel，纯 dict 实现，零新增依赖
"""
import json
from typing import Any, Dict, List, Optional, Tuple

_LOCALE = "zh"

# 核心 key → (zh, en)
_L10N: Dict[str, Tuple[str, str]] = {
    # 品牌
    "brand": ("爽点厂", "HookForge"),
    "brand_sub": ("HookForge", "HookForge"),
    "hero_title": ("一键出片", "One-Click Video Generation"),
    "hero_desc": ("粘贴剧本 → 选档位/画风/剧种 → 一键出片 · 给创作者的短剧视频工作流引擎",
                  "Paste script → pick tier/style/scenario → one-click video · "
                  "short-drama video workflow engine for creators"),

    # 卡片标题
    "card_script": ("① 粘贴你的剧本", "① Paste Your Script"),
    "card_config": ("② 选择出片配置", "② Select Generation Settings"),
    "card_result": ("③ 出片结果", "③ Results"),

    # 表单 label
    "label_tier": ("档位（你的电脑配置）", "Tier (your GPU tier)"),
    "label_style": ("画风", "Art Style"),
    "label_scenario": ("剧种（决定 BGM/配音）", "Genre (drives BGM/voice)"),
    "label_ep": ("本集分镜数", "Shot count per episode"),

    # 占位符
    "placeholder_script": ("第1场：男主进屋看到刀，神色凝重\n第2场：男主拿起刀冲向门口\n（支持 markdown 标题；建议 3-10 场/集）",
                            "Scene 1: Hero enters, sees the knife, grows grim\nScene 2: Hero grabs it and charges out\n(markdown headings OK; 3-10 scenes per episode recommended)"),
    "tip_script": ("💡 写清每场动作+情绪，效果最好。剧种决定 BGM/配音风格，画风决定画面质感。",
                    "💡 Describe actions + emotions clearly. Genre drives BGM/voice; style drives visuals."),
    "tip_tier": ("🖥 不确定选哪档？1060/1650 选 T1；轻薄本无独显选 T0；3060/4060 选 T2。",
                 "🖥 Unsure? 1060/1650 → T1; thin laptop → T0; 3060/4060 → T2."),

    # 按钮 / 状态
    "btn_run": ("🎬 一键出片", "🎬 Generate"),
    "btn_run_running": ("出片中…", "Generating…"),
    "status_running": ("⏳ 正在出片，请稍候（30秒~2分钟）…", "⏳ Generating, please wait (30s~2min)…"),
    "status_ok": ("✓ 出片成功！", "✓ Video ready!"),
    "status_fail": ("✗ 出片失败", "✗ Generation failed"),
    "btn_download": ("⬇ 下载成片", "⬇ Download video"),

    # 环节
    "stage_script_struct": ("拆解剧本", "Script parse"),
    "stage_bgm": ("选BGM", "Pick BGM"),
    "stage_character_image": ("画角色", "Draw characters"),
    "stage_storyboard_prompt": ("生成分镜", "Generate storyboard"),
    "stage_video_shot": ("渲染视频", "Render video"),
    "stage_fx_enhance": ("加特效", "Apply FX"),
    "stage_post_assemble": ("合成成片", "Assemble video"),
    "stage_bgm_audio": ("配BGM", "Mix BGM"),
    "stage_package_publish": ("打包发布", "Package & publish"),

    # 错误
    "err_empty_script": ("剧本不能为空，请先粘贴剧本内容", "Script is empty, please paste content first"),
}

# 下拉选项（value 不变，label 双语）
_STYLE_OPTIONS_BI: List[Tuple[str, str, str]] = [
    ("S1_anime_jp", "日系动漫", "JP Anime"),
    ("S2_korean_cool", "韩系冷感", "Korean Cool"),
    ("S3_cn_shuimo", "中国水墨", "CN Ink Wash"),
    ("S4_realistic", "写实", "Realistic"),
    ("S5_mmd_2d", "MMD二次元", "MMD 2D"),
    ("S6_shounen_manga", "少年漫画", "Shounen Manga"),
    ("S7_shoujo_manga", "少女漫画", "Shoujo Manga"),
    ("S8_dark_gothic", "暗黑哥特", "Dark Gothic"),
    ("S9_cyberpunk", "赛博朋克", "Cyberpunk"),
    ("S10_steampunk", "蒸汽朋克", "Steampunk"),
    ("S11_lowpoly", "低多边形", "Low Poly"),
    ("S12_thick_paint", "厚涂", "Thick Paint"),
    ("S13_watercolor", "水彩", "Watercolor"),
    ("S14_flat_illustration", "扁平插画", "Flat Illustration"),
    ("S15_pixel_90s", "90s像素", "90s Pixel"),
    ("S16_film_photo", "胶片摄影", "Film Photo"),
    ("S17_doc_real", "纪实写实", "Docu Real"),
    ("S18_cel_3d", "卡通3D", "Cartoon 3D"),
    ("S19_ink_brush_cn", "国风水墨", "CN Ink Brush"),
    ("S20_photoreal_8k", "超写实8K", "Photoreal 8K"),
]
_SCENARIO_OPTIONS_BI: List[Tuple[str, str, str]] = [
    ("light_comedy", "轻喜剧", "Light Comedy"),
    ("daily_romance", "日常恋爱", "Daily Romance"),
    ("male_revenge", "男频复仇", "Male Revenge"),
    ("dark_thriller", "暗黑惊悚", "Dark Thriller"),
    ("fantasy_wuxia", "玄幻武侠", "Fantasy Wuxia"),
    ("romance_sad", "虐恋", "Angst Romance"),
    ("sci_fi_cyber", "科幻赛博", "Sci-Fi Cyber"),
    ("action_battle", "动作打斗", "Action Battle"),
    ("family_warm", "家庭温情", "Family Warmth"),
    ("school_youth", "校园青春", "School Youth"),
]
_TIER_OPTIONS_BI: List[Tuple[str, str, str]] = [
    ("T0", "T0 · 无独显（纯云端出片）", "T0 · no dGPU (cloud-only)"),
    ("T1", "T1 · 入门独显 6GB（性价比之王）", "T1 · entry dGPU 6GB (bang-per-byte)"),
    ("T2", "T2 · 中端独显 8-12GB", "T2 · mid dGPU 8-12GB"),
]


def set_locale(loc: str) -> str:
    """切换 locale：'zh' 或 'en'。返回当前生效 locale。"""
    global _LOCALE
    if loc not in ("zh", "en"):
        loc = "zh"
    _LOCALE = loc
    return _LOCALE


def get_locale() -> str:
    return _LOCALE


def t(key: str) -> str:
    """按当前 locale 取文案。key 不存在时返回 key 本身。"""
    if key not in _L10N:
        return key
    return _L10N[key][0] if _LOCALE == "zh" else _L10N[key][1]


def style_options() -> List[Tuple[str, str]]:
    """当前 locale 的画风下拉选项 [(value, label)]。"""
    idx = 1 if _LOCALE == "zh" else 2
    return [(item[0], item[idx]) for item in _STYLE_OPTIONS_BI]


def scenario_options() -> List[Tuple[str, str]]:
    idx = 1 if _LOCALE == "zh" else 2
    return [(item[0], item[idx]) for item in _SCENARIO_OPTIONS_BI]


def tier_options() -> List[Tuple[str, str]]:
    idx = 1 if _LOCALE == "zh" else 2
    return [(item[0], item[idx]) for item in _TIER_OPTIONS_BI]


def all_options() -> Dict[str, List[Tuple[str, str]]]:
    return {"styles": style_options(), "scenarios": scenario_options(),
            "tiers": tier_options()}


def all_ui_text() -> Dict[str, str]:
    """当前 locale 下所有 UI 文案（key → 文案），供模板渲染。"""
    return {k: t(k) for k in _L10N}


def l10n_js() -> str:
    """构造前端 window.L10N 的 JSON 字面量（JS 安全）。"""
    stages = {}
    stage_map = {
        "script_struct": "stage_script_struct",
        "bgm": "stage_bgm",
        "character_image": "stage_character_image",
        "storyboard_prompt": "stage_storyboard_prompt",
        "video_shot": "stage_video_shot",
        "fx_enhance": "stage_fx_enhance",
        "post_assemble": "stage_post_assemble",
        "bgm_audio": "stage_bgm_audio",
        "package_publish": "stage_package_publish",
    }
    for sid, key in stage_map.items():
        stages[sid] = t(key)
    payload = {
        "running": t("status_running"),
        "ok": t("status_ok"),
        "fail": t("status_fail"),
        "running_btn": t("btn_run_running"),
        "err_empty": t("err_empty_script"),
        "stages": stages,
    }
    return json.dumps(payload, ensure_ascii=False)
