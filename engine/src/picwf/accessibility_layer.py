# -*- coding: utf-8 -*-
"""accessibility_layer：三方对标后的平民化体验层。

把 LibTV/ComfyUI/即梦 对比结论落成引擎能力：
- 三档模式（新手/进阶/专家）
- 成本透明（耗时/显存/成本预估）
- 失败可懂（人话原因 + 3 条 fallback）
"""
from typing import Any, Dict, List, Optional

MODES = {"beginner", "pro", "expert"}


def _cost_text(cost: float) -> str:
    if cost < 0.5:
        return "本地低成本"
    if cost < 1.5:
        return "中等成本"
    return "云端较高成本"


def _vram_text(vram: float) -> str:
    if vram <= 6:
        return "低显存可跑"
    if vram <= 12:
        return "中高显存更稳"
    return "需高端显存/云端"


def mode_params(mode: str, ctx: Dict[str, Any] = None) -> Dict[str, Any]:
    """按模式给默认参数（新手最简，专家全量）。"""
    ctx = ctx or {}
    tier = ctx.get("tier", "T1")
    if mode == "beginner":
        params = {
            "style_strength": 0.75,
            "resolution": 480 if tier in {"T0", "T1"} else 720,
            "steps": 20 if tier in {"T0", "T1"} else 28,
            "quality_target": 0.8,
        }
    elif mode == "pro":
        params = {
            "style_strength": 0.82,
            "resolution": 720,
            "steps": 28,
            "quality_target": 0.85,
            "negative_prompt": "blurry, low quality, watermark",
        }
    else:
        params = {
            "style_strength": 0.88,
            "resolution": 1080,
            "steps": 36,
            "quality_target": 0.9,
            "negative_prompt": "blurry, low quality, watermark, deformed",
            "sampler": "dpmpp_2m_sde",
        }
    return {"mode": mode, "params": params}


def cost_visibility(plan: Dict[str, Any]) -> Dict[str, Any]:
    """把 efficiency plan 转成“用户看得懂”的成本面板。"""
    best = plan.get("best") or {}
    paths = plan.get("paths") or []
    options = []
    for p in paths[:3]:
        options.append({
            "model_id": p.get("model_id"),
            "cloud": p.get("cloud"),
            "cost_label": _cost_text(float(p.get("cost") or 1.0)),
            "vram_label": _vram_text(float(p.get("estimated_vram_gb") or 0)),
            "quality_score": p.get("quality"),
            "speed_label": "快" if float(p.get("speed") or 1.0) >= 1.0 else "中等",
        })
    return {
        "primary": options[0] if options else None,
        "options": options,
        "note": "本地优先，云端兜底；失败会先重试本地路径",
    }


def friendly_failure(plan: Dict[str, Any], qa_summary: Dict[str, Any] = None) -> Dict[str, Any]:
    """把失败信息成人话输出，并给 3 条可执行 fallback。"""
    qa_summary = qa_summary or {}
    failures = int(qa_summary.get("failed") or 0)
    total = int(qa_summary.get("total") or 0)
    gate = (plan.get("best") or {}).get("resource_ok", True)
    reason = "未知问题"
    if failures and total:
        reason = f"有 {failures}/{total} 个镜头未通过质检"
    elif gate is False:
        reason = "当前机器资源可能不够，先走本地低配路径或云端兜底"
    fallbacks = []
    paths = plan.get("paths") or []
    for p in paths[:3]:
        fallbacks.append({
            "model_id": p.get("model_id"),
            "why": "成本更低" if not p.get("cloud") else "质量更高",
            "resource_ok": p.get("resource_ok"),
        })
    return {"reason": reason, "fallbacks": fallbacks}
