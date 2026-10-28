# -*- coding: utf-8 -*-
"""comic_drama_pipeline: 漫剧三环节链路串联（角色卡 → 分镜 → 运动）。

定位(白皇 2026-10-28): 光有单模板渲染不算"互通"，必须把上一环节的真实输出
接进下一环节的输入，链路才成立。本模块负责：

1. character_sheet 按 variant_count 循环出 N 张角色参考图 → char_v0..N.png
2. storyboard 用 char_v0.png 作 character_ref，按 frames_per_shot 循环出帧序列
   → story_f0..M.png（seed 递增保证帧间有变化）
3. motion 用 story_f0.png(首帧) + story_fM.png(尾帧) 驱动 → motion_clip.mp4

同时做链路级预检：档位是否支持全链路、每环节是否有残留占位符/悬空引用。
T1 只支持 character_sheet，会明确报出链路断点，而不是跑到一半炸掉。

设计原则: 只做数据编排与校验，不真的调用 ComfyUI。
真实提交由 comfyui_runner 拿这里产出的 prompt 逐条 POST /prompt。
"""
import os
from typing import Any, Dict, List, Optional

from . import comic_drama_workflow as cdw

# 链路定义：上游 stage → 上游输出 → 下游 stage → 下游输入
PIPELINE_LINKS = [
    {"from": "character_sheet", "output": "char_v0.png",
     "to": "storyboard", "input": "character_ref"},
    {"from": "storyboard", "output": "story_f0.png",
     "to": "motion", "input": "first_frame"},
    {"from": "storyboard", "output": "story_f{last}.png",
     "to": "motion", "input": "last_frame"},
]

STAGE_ORDER = ["character_sheet", "storyboard", "motion"]


def _stage_outputs(stage: str, ctx: Dict[str, Any]) -> List[str]:
    """按模板声明的输出规则，算出该环节实际会产出的文件名列表。"""
    if stage == "character_sheet":
        n = int(ctx.get("variant_count") or 4)
        return ["char_v%d.png" % i for i in range(n)]
    if stage == "storyboard":
        n = int(ctx.get("frames_per_shot") or 3)
        return ["story_f%d.png" % i for i in range(n)]
    if stage == "motion":
        return ["motion_clip.mp4"]
    return []


def _render_stage(stage: str, overrides: Dict[str, Any], tier: str,
                  dir_path: Optional[str] = None) -> Dict[str, Any]:
    """渲染单环节的产物集合（按 variant/frame 循环）。"""
    tpl = cdw.load_template(stage, dir_path)
    base_ctx = dict(tpl.get("inputs", {}))
    base_ctx.update(overrides or {})

    if stage == "character_sheet":
        count_key, loop_len = "variant_count", int(base_ctx.get("variant_count") or 4)
    elif stage == "storyboard":
        count_key, loop_len = "frames_per_shot", int(base_ctx.get("frames_per_shot") or 3)
    else:
        count_key, loop_len = None, 1

    prompts = []
    issues: List[str] = []
    warnings: List[str] = []
    outputs: List[str] = []

    for i in range(loop_len):
        ov = dict(base_ctx)
        if stage == "character_sheet":
            ov["variant"] = i
        elif stage == "storyboard":
            ov["frame"] = i
            # seed 递增：保证多帧之间有差异，而非同一张图重复
            base_seed = int(base_ctx.get("seed") or 0)
            ov["seed"] = base_seed + i
        r = cdw.render_workflow(stage, overrides=ov, tier=tier, dir_path=dir_path)
        stage_issues = cdw.validate_rendered(r["workflow"])
        for issue in stage_issues:
            issues.append("帧%d: %s" % (i, issue))
        for w in r["warnings"]:
            if w not in warnings:
                warnings.append(w)
        prompts.append(r["workflow"])
        outputs.append(_stage_outputs(stage, ov)[min(i, len(_stage_outputs(stage, ov)) - 1)])

    return {
        "stage": stage,
        "tier": tier,
        "version": _version(stage),
        "prompts": prompts,
        "count": len(prompts),
        "outputs": outputs,
        "issues": issues,
        "warnings": warnings,
        "valid": not issues,
    }


def _version(stage: str) -> str:
    return {"character_sheet": "character_ref_sheet",
            "storyboard": "storyboard_frames",
            "motion": "motion_clip"}.get(stage, stage)


def render_pipeline(tier: str = "T3",
                    character_overrides: Optional[Dict[str, Any]] = None,
                    story_overrides: Optional[Dict[str, Any]] = None,
                    motion_overrides: Optional[Dict[str, Any]] = None,
                    dir_path: Optional[str] = None) -> Dict[str, Any]:
    """渲染完整漫剧链路，自动把上游输出接进下游输入。

    返回:
      {
        "tier": str,
        "stages": [每环节渲染结果],
        "links": [实际生效的衔接],
        "blocking": [阻断性问题（档位不支持/渲染失败）],
        "ok": bool,            # 链路可跑通
        "can_instantiate": bool # 是否可提交给 ComfyUI
      }
    """
    char_ov = dict(character_overrides or {})
    story_ov = dict(story_overrides or {})
    motion_ov = dict(motion_overrides or {})

    stages: List[Dict[str, Any]] = []
    links_effective: List[Dict[str, Any]] = []
    blocking: List[str] = []

    # ---- 1. 角色卡 ----
    char_stage = _render_stage("character_sheet", char_ov, tier, dir_path)
    stages.append(char_stage)
    if not char_stage["valid"]:
        blocking.append("character_sheet 渲染失败: %s" % char_stage["issues"])
    char_ref = char_stage["outputs"][0] if char_stage["outputs"] else "char_v0.png"

    # ---- 2. 分镜（注入角色参考图）----
    story_ov.setdefault("character_ref", char_ref)
    story_stage = _render_stage("storyboard", story_ov, tier, dir_path)
    stages.append(story_stage)
    links_effective.append({
        "from": "character_sheet", "output": char_ref,
        "to": "storyboard", "input": "character_ref",
        "status": "ok" if char_stage["valid"] else "上游失败",
    })
    if not story_stage["valid"]:
        blocking.append("storyboard 渲染失败: %s" % story_stage["issues"])
    if stage_tier_unsupported("storyboard", tier, dir_path):
        blocking.append("当前档位 %s 不支持 storyboard（需 %s）"
                        % (tier, _tier_compat("storyboard", dir_path)))

    # ---- 3. 运动（首尾帧驱动）----
    frames = story_stage["outputs"]
    first_frame = frames[0] if frames else "story_f0.png"
    last_frame = frames[-1] if frames else "story_f2.png"
    motion_ov.setdefault("first_frame", first_frame)
    motion_ov.setdefault("last_frame", last_frame)
    motion_stage = _render_stage("motion", motion_ov, tier, dir_path)
    stages.append(motion_stage)
    links_effective.append({
        "from": "storyboard", "output": first_frame,
        "to": "motion", "input": "first_frame",
        "status": "ok" if story_stage["valid"] else "上游失败",
    })
    links_effective.append({
        "from": "storyboard", "output": last_frame,
        "to": "motion", "input": "last_frame",
        "status": "ok" if story_stage["valid"] else "上游失败",
    })
    if not motion_stage["valid"]:
        blocking.append("motion 渲染失败: %s" % motion_stage["issues"])
    if stage_tier_unsupported("motion", tier, dir_path):
        blocking.append("当前档位 %s 不支持 motion（需 %s），可走云端兜底 %s"
                        % (tier, _tier_compat("motion", dir_path),
                           _cloud_fallback("motion", dir_path)))

    return {
        "tier": tier,
        "stages": stages,
        "links": links_effective,
        "blocking": blocking,
        "ok": not blocking,
        "can_instantiate": not blocking,
    }


def _tier_compat(stage: str, dir_path=None) -> List[str]:
    try:
        return cdw.load_template(stage, dir_path).get("tier_compat") or []
    except Exception:
        return []


def _cloud_fallback(stage: str, dir_path=None) -> str:
    try:
        return cdw.load_template(stage, dir_path).get("cloud_fallback") or ""
    except Exception:
        return ""


def stage_tier_unsupported(stage: str, tier: str, dir_path=None) -> bool:
    """当前档位是否跑不了该环节。"""
    compat = _tier_compat(stage, dir_path)
    return bool(compat) and tier not in compat


def pipeline_summary(result: Dict[str, Any]) -> str:
    """人读的链路摘要，方便日志/CLI 输出。"""
    lines = ["漫剧链路 tier=%s  ok=%s" % (result.get("tier"), result.get("ok"))]
    for st in result.get("stages", []):
        lines.append("  [%s] %d 帧/变体 -> %s  档位告警%d 问题%d"
                     % (st["stage"], st["count"], ",".join(st["outputs"][:3]),
                        len(st["warnings"]), len(st["issues"])))
    for lk in result.get("links", []):
        lines.append("  链接 %s.%s -> %s.%s [%s]"
                     % (lk["from"], lk["output"], lk["to"], lk["input"], lk["status"]))
    for b in result.get("blocking", []):
        lines.append("  阻断: %s" % b)
    return "\n".join(lines)


__all__ = ["PIPELINE_LINKS", "STAGE_ORDER", "render_pipeline",
           "stage_tier_unsupported", "pipeline_summary"]
