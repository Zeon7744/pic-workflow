# -*- coding: utf-8 -*-
"""param_advisor：全模块参数辅助建议。

给每个引擎模块输出“推荐值 + 可选范围 + 风险提示 + 资源约束”。
用途：
- 用户不熟参数时，系统自动给出可执行建议
- 前端/CLI 可据此做默认值填充与校验
- 全模块铺开迭代时，统一入口 advise_all(ctx)
"""
from typing import Any, Dict

def _s(key: str, suggested: Any, help_text: str, risk: str = "", resource: str = "") -> Dict[str, Any]:
    return {
        "key": key,
        "suggested": suggested,
        "help": help_text,
        "risk": risk,
        "resource": resource,
    }

def advise_module(module: str, ctx: Dict[str, Any] = None) -> Dict[str, Any]:
    """按模块名输出参数建议。"""
    ctx = ctx or {}
    if module == "script":
        return {
            "module": "script",
            "params": [
                _s("shots_per_ep", ctx.get("shots_per_ep", 10), "每集镜头数",
                   risk="镜头越多，总耗时与显存压力越高",
                   resource="每多1镜约增加5-15s"),
                _s("script_text", ctx.get("script_text", ""), "剧本/对白原文",
                   risk="空文本会触发兜底镜头"),
                _s("use_llm", ctx.get("use_llm", True), "是否启用LLM拆解",
                   risk="无LLM时自动回退规则拆解"),
                _s("style_hint", ctx.get("style_hint", "auto"), "风格倾向(auto/realistic/anime/cg)",
                   risk="非auto会降低题材泛化能力"),
            ],
            "defaults": {"shots_per_ep": 10, "use_llm": True, "style_hint": "auto"},
        }
    if module == "character":
        return {
            "module": "character",
            "params": [
                _s("name", ctx.get("name", "主角"), "角色名"),
                _s("role", ctx.get("role", "主角"), "角色类型(主角/配角/反派)"),
                _s("age_band", ctx.get("age_band", "25-32岁"), "年龄段",
                   risk="建议精确年龄段，避免『年轻/中年』模糊词"),
                _s("hair", ctx.get("hair", "黑色中分微卷"), "发型",
                   risk="建议写长度+形态，避免『长发/短发』模糊词"),
                _s("outfit", ctx.get("outfit", "简约都市通勤装"), "服装",
                   risk="建议写主色+材质+细节"),
                _s("temperament", ctx.get("temperament", "冷峻克制"), "气质基调"),
            ],
            "defaults": {"role": "主角", "age_band": "25-32岁", "hair": "黑色中分微卷",
                         "outfit": "简约都市通勤装", "temperament": "冷峻克制"},
        }
    if module == "prompt":
        return {
            "module": "prompt",
            "params": [
                _s("topic", ctx.get("topic", "现实"), "题材(auto/现实/古装/科幻/悬疑/甜宠/恐怖)"),
                _s("extra_detail", ctx.get("extra_detail", ""), "补充细节，建议1-3句"),
                _s("enable_human_layer", ctx.get("enable_human_layer", True), "启用人性化情绪层"),
                _s("character_lock", ctx.get("character_lock", True), "启用角色逐字特征锁定"),
            ],
            "defaults": {"topic": "现实", "extra_detail": "", "enable_human_layer": True,
                         "character_lock": True},
        }
    if module == "video":
        tier = ctx.get("tier", "T1")
        free = float(ctx.get("free_vram_gb", 6.0))
        low_vram = tier in ("T0", "T1") and free <= 8
        if low_vram:
            default_impl = "wan13b_gguf_q4_offload_480"
            default_res = "480p"
            risk = "T1低显存：优先Q4+offload，避免本地FP16大模型"
            steps = 20
        else:
            default_impl = "wan13b_fp16_720"
            default_res = "720p"
            risk = "高显存可上720p，但生成耗时显著增加"
            steps = 28
        return {
            "module": "video",
            "params": [
                _s("model_impl", default_impl, "模型实现", risk=risk, resource="显存/耗时强相关"),
                _s("resolution", default_res, "分辨率", risk="1060建议不高于720p"),
                _s("steps", steps, "采样步数", risk="步数越多越耗时间"),
                _s("cfg", 7.5, "CFG强度", risk="过高易过拟合文本"),
                _s("use_skeleton_chain", True, "启用首尾帧骨架传递"),
                _s("single_motion_lock", True, "启用单镜单运镜锁定"),
            ],
            "defaults": {"model_impl": default_impl, "resolution": default_res,
                         "steps": steps, "cfg": 7.5, "use_skeleton_chain": True,
                         "single_motion_lock": True},
        }
    if module == "audio":
        return {
            "module": "audio",
            "params": [
                _s("music_track", ctx.get("music_track", "M04_city_warm"), "音乐轨"),
                _s("voice_track", ctx.get("voice_track", "V03_calm_female"), "旁白轨"),
                _s("bgm_track", ctx.get("bgm_track", "B08_suspense_cold"), "BGM轨"),
                _s("auto_mute_conflict", ctx.get("auto_mute_conflict", True),
                   "自动规避人声/BGM冲突"),
            ],
            "defaults": {"music_track": "M04_city_warm", "voice_track": "V03_calm_female",
                         "bgm_track": "B08_suspense_cold", "auto_mute_conflict": True},
        }
    if module == "qa":
        return {
            "module": "qa",
            "params": [
                _s("threshold_shape", 0.83, "形变阈值", risk="过低会放过走形"),
                _s("threshold_style", 0.78, "质变阈值"),
                _s("threshold_place", 0.75, "迁移阈值"),
                _s("threshold_intent", 0.80, "偏移阈值"),
                _s("auto_requeue", True, "未过线自动进重做队列"),
            ],
            "defaults": {"threshold_shape": 0.83, "threshold_style": 0.78,
                         "threshold_place": 0.75, "threshold_intent": 0.80,
                         "auto_requeue": True},
        }
    if module == "resource":
        return {
            "module": "resource",
            "params": [
                _s("free_vram_gb", ctx.get("free_vram_gb", 6.0), "可用显存(GB)"),
                _s("prefer_cost", ctx.get("prefer_cost", True), "低成本优先"),
                _s("prefer_speed", ctx.get("prefer_speed", False), "速度优先"),
                _s("enable_cloud_fallback", ctx.get("enable_cloud_fallback", True),
                   "OOM/超时自动云端兜底"),
            ],
            "defaults": {"free_vram_gb": 6.0, "prefer_cost": True, "prefer_speed": False,
                         "enable_cloud_fallback": True},
        }
    return {"module": module, "params": [], "defaults": {}, "unknown_module": True}


def advise_all(ctx: Dict[str, Any] = None) -> Dict[str, Any]:
    """一次性输出全模块参数建议（整体铺开迭代入口）。"""
    ctx = ctx or {}
    modules = ["script", "character", "prompt", "video", "audio", "qa", "resource"]
    out = {m: advise_module(m, ctx) for m in modules}
    out["_summary"] = {
        "module_count": len(modules),
        "suggested_keys": sum(len(v.get("params", [])) for v in out.values() if isinstance(v, dict)),
    }
    return out
