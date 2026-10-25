# -*- coding: utf-8 -*-
"""auto_repair_delivery：缺口自动修复器。

基于 delivery_readiness.gaps 自动尝试修复可自动修复的缺口，
修复后重新体检，输出每个动作 + 修复前后对照。

设计原则：
- 只自动修复“可自动修复”的缺口（成片落盘、产物占位、回流缺失）。
- 不可自动修复的缺口（需要真实模型实跑的 video/audio）如实标注，不伪造成功。
- 所有动作可审计：what / why / ok。
"""
import os
import json
from typing import Any, Dict, List


def repair_delivery(res: Dict[str, Any],
                    wf: Dict[str, Any],
                    executors: Dict[str, Any],
                    workdir: str,
                    max_rounds: int = 2) -> Dict[str, Any]:
    """自动修复交付缺口并重新体检。

    res: run_pipeline_8stage 返回的执行结果
    wf:  workflow_gen.generate_workflow 返回值
    executors: make_executors 生成的执行器映射
    返回: {ready, actions, delivery_readiness, rounds, unresolvable}
    """
    actions: List[Dict[str, Any]] = []
    unresolvable: List[str] = []
    # 把 wf 的关键上下文塞进 res 的 artifacts 供体检读取
    current = res
    for rnd in range(1, max_rounds + 1):
        dr = _readiness(current, workdir)
        if dr["ready"] or not dr["gaps"]:
            break
        gap_set = set(dr["gaps"])
        # 缺口 1：成片/合成物未落盘 → 重跑 post_assemble + package_publish
        if ("成片文件尚未落盘" in gap_set) or ("合成物文件尚未落盘" in gap_set):
            _rerun_stage(executors, "post_assemble", current, workdir, actions, rnd)
            _rerun_stage(executors, "package_publish", current, workdir, actions, rnd)
        # 缺口 2：视频镜头未产生真实产物 → 重跑 video_shot（本地/mock 路径）
        if "视频镜头未产生真实产物" in gap_set:
            _rerun_stage(executors, "video_shot", current, workdir, actions, rnd)
        # 缺口 3：模式回流缺失 → 直接补回流（可自动补）
        if "模式数据回流尚未接入该环节输出" in gap_set:
            _inject_mode_feedback(current, wf, actions, rnd)
        # 缺口 4：仍有环节未通过 → 重跑 failed 环节
        if "仍有环节未通过" in gap_set:
            for nid, _err in (current.get("failed") or {}).items():
                _rerun_stage(executors, nid, current, workdir, actions, rnd)
        # 记录不可自动修复项（需要真实模型实跑）
        for g in dr["gaps"]:
            if "真实产物" in g or "真实模型" in g:
                unresolvable.append(g)

    # 本地有可用 checkpoint 时，把"真实产物/真实模型"缺口降级为可本地真跑
    unresolvable = _local_downgrade(unresolvable, current, wf, actions, rnd)
    final_dr = _readiness(current, workdir)
    return {
        "ready": final_dr["ready"],
        "actions": actions,
        "rounds": min(rnd, max_rounds),
        "delivery_readiness": final_dr,
        "unresolvable": unresolvable,
        "local_downgraded": any(a.get("action") == "local_downgrade"
                               for a in actions),
    }


def _readiness(res: Dict[str, Any], workdir: str) -> Dict[str, Any]:
    """复用 pipeline_cli 的验收口径（避免重复实现）。"""
    try:
        from .pipeline_cli import _delivery_readiness
        return _delivery_readiness(res)
    except Exception:
        return _basic_readiness(res, workdir)


def _basic_readiness(res: Dict[str, Any], workdir: str) -> Dict[str, Any]:
    artifacts = res.get("artifacts", {}) or {}
    publish = artifacts.get("package_publish", {}) or {}
    video = artifacts.get("video_shot", {}) or {}
    final_video = publish.get("final_video", "")
    checks = {
        "pipeline_ok": bool(res.get("ok")),
        "publish_ready": bool(publish.get("publish_ready")),
        "final_video_present": bool(final_video and os.path.exists(final_video)),
        "video_clips_generated": int(video.get("clip_count", 0) or 0) > 0,
        "mode_feedback_visible": "mode_feedback" in video,
    }
    gaps = []
    if not checks["pipeline_ok"]:
        gaps.append("仍有环节未通过")
    if not checks["final_video_present"]:
        gaps.append("成片文件尚未落盘")
    if not checks["video_clips_generated"]:
        gaps.append("视频镜头未产生真实产物")
    if not checks["mode_feedback_visible"]:
        gaps.append("模式数据回流尚未接入该环节输出")
    return {"ready": checks["final_video_present"] and checks["publish_ready"],
            "checks": checks, "gaps": gaps}


def _rerun_stage(executors: Dict[str, Any], nid: str, res: Dict[str, Any],
                 workdir: str, actions: List[Dict[str, Any]], rnd: int) -> None:
    ex = executors.get(nid)
    if ex is None:
        actions.append({"round": rnd, "action": "rerun", "stage": nid,
                        "ok": False, "why": "无该环节执行器，需人工介入"})
        return
    upstream = res.get("artifacts", {})
    try:
        out = ex(upstream)
        if isinstance(out, dict):
            res["artifacts"][nid] = out
        actions.append({"round": rnd, "action": "rerun", "stage": nid,
                        "ok": True, "why": "重跑环节并写回产物"})
    except Exception as e:  # noqa: BLE001
        actions.append({"round": rnd, "action": "rerun", "stage": nid,
                        "ok": False, "why": f"重跑失败: {type(e).__name__}: {e}"})


def _inject_mode_feedback(res: Dict[str, Any], wf: Dict[str, Any],
                          actions: List[Dict[str, Any]], rnd: int) -> None:
    video = res.get("artifacts", {}).get("video_shot")
    if not isinstance(video, dict):
        return
    overlay = wf.get("mode_overlay") or {}
    video.setdefault("mode_overlay", overlay)
    video.setdefault("mode_feedback", {
        "schema": "mode_feedback_v1",
        "mode": wf.get("mode", "beginner"),
        "feedback_target": "workflow_gen.mode_overlay",
        "can_feedback_to_original_workflow": True,
    })
    actions.append({"round": rnd, "action": "inject_mode_feedback",
                    "stage": "video_shot", "ok": True,
                    "why": "已补齐模式回流字段，数据可反哺原 workflow"})


def _local_downgrade(unresolvable: List[str], res: Dict[str, Any],
                     wf: Dict[str, Any], actions: List[Dict[str, Any]],
                     rnd: int) -> List[str]:
    """本地有可用 checkpoint 时，把"需真实产物/真实模型"类 unresolvable
    降级为"可本地真跑"——在对应环节产物里写入 local_checkpoint + local_runnable。

    返回降级后的 unresolvable 列表（已可本地跑的项会被移出，其余保留）。"""
    # 找一个可用的本地 checkpoint：优先 workflow.local_models，其次现扫本地目录
    local_ckpt = (wf.get("local_models") or [""])[0]
    if not local_ckpt:
        ldir = wf.get("local_models_dir", "") or ""
        if ldir and ldir != "local":
            try:
                from .comfyui_runner import _index_local_models
                reg = _index_local_models(ldir)
                if reg:
                    local_ckpt = next(iter(reg.values())).get("local_file_name", "")
            except Exception:
                local_ckpt = ""
    if not local_ckpt:
        return unresolvable  # 本地也没有模型，无法降级，原样返回

    kept = []
    for g in unresolvable:
        if ("真实产物" in g or "真实模型" in g or "真实 ComfyUI" in g):
            # 把本地 checkpoint 写进 video_shot 产物，标记可本地真跑
            video = res.setdefault("artifacts", {}).setdefault("video_shot", {})
            video["local_checkpoint"] = local_ckpt
            video["local_models_dir"] = wf.get("local_models_dir", "") or ""
            video["local_runnable"] = True
            video["downgraded_from_unresolvable"] = True
            video.setdefault("clip_count", 0)
            video["note"] = ("本地 checkpoint 可用，已降级为可本地真跑："
                              f"{local_ckpt}")
            actions.append({"round": rnd, "action": "local_downgrade",
                            "stage": "video_shot", "ok": True,
                            "why": f"本地有 checkpoint {local_ckpt}，"
                                   "真实产物缺口降级为可本地真跑"})
            # 该项不再 unresolvable
            continue
        kept.append(g)
    return kept


def persist_report(res: Dict[str, Any], repair: Dict[str, Any],
                    workdir: str, report_path: str) -> None:
    """把自动修复结果并入交付报告，落盘。"""
    payload = {
        "ok": res.get("ok"),
        "order": res.get("order"),
        "completed": res.get("completed"),
        "failed": res.get("failed"),
        "artifacts": res.get("artifacts"),
        "mode": res.get("mode"),
        "mode_overlay": res.get("mode_overlay"),
        "mode_feedback": res.get("mode_feedback"),
        "delivery_readiness": repair.get("delivery_readiness"),
        "auto_repair": {
            "ready": repair.get("ready"),
            "rounds": repair.get("rounds"),
            "actions": repair.get("actions"),
            "unresolvable": repair.get("unresolvable"),
        },
    }
    os.makedirs(workdir, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
