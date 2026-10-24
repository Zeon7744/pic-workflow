# -*- coding: utf-8 -*-
"""qa_loop：质量闭环执行层。

把“质检 → 路由 → 重试/换模型/降级/云端精修 → 复核”串成可执行闭环。
当前先做引擎内策略层：
- 输入已有 QAReport（qa_scoring）+ efficiency_planner 的多路径候选
- 输出闭环决策（accepted / retried / degraded / escalated / failed）
后续可接 orchestrator / pipeline_executors 主链路。
"""
from typing import Any, Dict, List, Optional

DEFAULT_POLICY = {
    "max_retries": 2,
    "prefer_local_first": True,
    "max_cost": 999.0,
    "escalate_to_cloud": True,
    "allow_degrade": True,
}


def _next_candidate_from_plan(plan: Dict[str, Any],
                              current_model: str,
                              path_index: int,
                              prefer_local_first: bool) -> Optional[Dict[str, Any]]:
    paths = plan.get("paths") or []
    if not paths:
        return None
    ordered = sorted(paths, key=lambda p: (
        0 if (prefer_local_first and not p.get("cloud")) else 1,
        -(p.get("score") or 0),
        p.get("model_id") or "",
    ))
    if current_model and prefer_local_first:
        for p in ordered:
            if p.get("model_id") != current_model:
                return p
    return ordered[path_index % len(ordered)]


def decide_qa_loop(report: Dict[str, Any],
                   plan: Dict[str, Any] = None,
                   current_model: str = "",
                   attempt: int = 0,
                   policy: Dict[str, Any] = None,
                   ) -> Dict[str, Any]:
    """按单镜头 QA 报告决定闭环动作。

    report: qa_scoring.QAReport.as_dict() 或同构 dict
    plan: efficiency_planner.plan_and_report 输出
    current_model: 当前正在用的模型
    attempt: 已经重试次数
    """
    pol = dict(DEFAULT_POLICY)
    pol.update(policy or {})
    plan = plan or {}
    gate = plan.get("gate", {})
    paths = plan.get("paths", [])
    current_score = (report.get("scores") or {}).get("alignment_intent", 0.0)
    prefer_local = bool(pol.get("prefer_local", True))

    # 通过：直接接受
    if report.get("passed") and report.get("route") == "pass":
        return {"action": "accepted", "model": current_model,
                "reason": "qa passed on first pass", "attempt": attempt}

    # 质量失败
    if report.get("route") == "redo_local":
        # 重试耗尽先拦截，避免 degrade/候选分支吞掉“重试已用完”的语义
        if attempt >= int(pol.get("max_retries", 2)):
            return {"action": "failed",
                    "reason": "retry budget exhausted on redo_local",
                    "model": current_model,
                    "attempt": attempt,
                    "gate": gate}
        # 本地重试，但尝试换路径候选
        if paths:
            cand = _next_candidate_from_plan(plan, current_model, attempt,
                                              pol.get("prefer_local_first", True))
            if cand:
                return {
                    "action": "retry_candidate",
                    "model": cand.get("model_id"),
                    "fallback_model": cand.get("model_id"),
                    "cloud": cand.get("cloud"),
                    "reason": f"redo_local, switch to candidate {cand.get('model_id')}",
                    "attempt": attempt + 1,
                    "resource_ok": cand.get("resource_ok"),
                }
        if pol.get("allow_degrade", True):
            return {"action": "degrade_params",
                    "reason": "quality fail, tighten steps/res within current model",
                    "model": current_model,
                    "attempt": attempt + 1}

    if report.get("route") == "cloud_refine":
        # 需要云端精修，若允许则优先 cloud 路径
        cloud_paths = [p for p in paths if p.get("cloud")]
        if pol.get("escalate_to_cloud", True) and cloud_paths:
            cloud_paths.sort(key=lambda p: (-(p.get("score") or 0), p.get("model_id") or ""))
            pick = cloud_paths[0]
            return {"action": "escalate_cloud",
                    "model": pick.get("model_id"),
                    "cloud": True,
                    "reason": f"cloud_refine -> {pick.get('model_id')}",
                    "attempt": attempt + 1}
        # 不允许云或没有云路径
        if attempt < int(pol.get("max_retries", 2)):
            cand = _next_candidate_from_plan(plan, current_model, attempt,
                                              pol.get("prefer_local_first", True))
            if cand:
                return {"action": "retry_candidate",
                        "model": cand.get("model_id"),
                        "reason": f"cloud_refine unavailable, fallback to {cand.get('model_id')}",
                        "attempt": attempt + 1}

    # 其他失败或耗尽重试
    if attempt >= int(pol.get("max_retries", 2)) or not report.get("passed"):
        return {"action": "failed",
                "reason": f"exhausted retries or unrecoverable quality fail (score={current_score:.3f})",
                "model": current_model,
                "attempt": attempt,
                "gate": gate}

    return {"action": "accepted", "model": current_model,
            "reason": "qa passed", "attempt": attempt}


def summarize_qa_loop(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """聚合多镜头闭环结果，输出看板字段。"""
    total = len(decisions)
    accepted = sum(1 for d in decisions if d.get("action") == "accepted")
    retried = sum(1 for d in decisions if d.get("action") in {"retry_candidate", "degrade_params"})
    escalated = sum(1 for d in decisions if d.get("action") == "escalate_cloud")
    failed = sum(1 for d in decisions if d.get("action") == "failed")
    return {
        "total": total,
        "accepted": accepted,
        "retried": retried,
        "escalated": escalated,
        "failed": failed,
        "pass_rate": (accepted / total) if total else 0.0,
        "needs_cloud": bool(escalated),
        "has_failure": bool(failed),
    }
