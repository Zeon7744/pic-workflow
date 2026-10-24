# -*- coding: utf-8 -*-
"""efficiency_planner：资源/成本/速度最优路径选择。

输入：
- registry: 多模型注册表（model_registry）
- profile: 硬件资源 profile（gpu.vram_gb 等）
- task: 任务需求（kind/quality_min/max_cost/budget）
输出：
- best + alternatives + gate + resource_dashboard（可导出 JSON/CSV）
"""
from typing import Any, Dict, List, Optional

def _norm_cost(c: float) -> float:
    return max(0.1, float(c or 1.0))

def plan_paths(registry: Dict[str, Dict[str, Any]],
               profile: Dict[str, Any] = None,
               task: Dict[str, Any] = None,
               top_k: int = 3) -> Dict[str, Any]:
    """同一任务生成多条可执行路径（本地优先 + 云兜底 + 成本权衡）。"""
    task = task or {}
    kind = task.get("kind", "video")
    quality_min = float(task.get("quality_min", 0.8))
    max_cost = float(task.get("max_cost", 999.0))
    max_s = float(task.get("max_seconds", 999.0))

    from .model_registry import score_backend
    scored: List[Dict[str, Any]] = []
    for spec in registry.values():
        if spec.get("kind") not in {kind, "generic"}:
            continue
        sc = score_backend(spec, profile or {}, strategy={"cost_w": 0.4, "speed_w": 0.3, "quality_w": 0.3})
        if sc["quality"] < quality_min:
            continue
        if sc["cost"] > max_cost:
            continue
        if sc["speed"] > 0 and (1.0 / sc["speed"]) > max_s:
            continue
        scored.append(sc)
    prefer_local = bool(task.get("prefer_local", False))
    scored.sort(key=lambda x: (
        0 if (prefer_local and not x.get("cloud")) else 1,
        -x["score"],
        x["id"],
    ))

    paths = [
        {
            "path_id": f"p{i+1}",
            "model_id": s["id"],
            "kind": s["kind"],
            "cloud": s["cloud"],
            "cost": s["cost"],
            "speed": s["speed"],
            "quality": s["quality"],
            "resource_ok": s["resource_ok"],
            "score": s["score"],
            "estimated_vram_gb": s.get("min_vram_gb"),
        } for i, s in enumerate(scored[:top_k])
    ]
    best = paths[0] if paths else None
    gate = {
        "has_path": best is not None,
        "best_path": best["path_id"] if best else None,
        "fallback_cloud": bool(best and best["cloud"]) if best else False,
        "reason": "resource_cost_speed_quality_balanced" if best else "no_candidate",
        "prefer_local": bool(task.get("prefer_local", False)),
    }
    return {
        "kind": kind,
        "profile": profile or {},
        "paths": paths,
        "best": best,
        "gate": gate,
        "prefer_local": bool(task.get("prefer_local", False)),
    }

def to_dashboard(plan: Dict[str, Any]) -> Dict[str, Any]:
    """把 plan 输出压缩成资源看板（便于导 CSV/HTML）。"""
    best = plan.get("best") or {}
    return {
        "kind": plan.get("kind"),
        "best_model": best.get("model_id"),
        "best_cloud": best.get("cloud"),
        "best_score": best.get("score"),
        "best_cost": best.get("cost"),
        "best_quality": best.get("quality"),
        "best_speed": best.get("speed"),
        "path_count": len(plan.get("paths", [])),
        "gate": plan.get("gate", {}),
    }

def plan_and_report(registry: Dict[str, Dict[str, Any]],
                    profile: Dict[str, Any] = None,
                    task: Dict[str, Any] = None) -> Dict[str, Any]:
    """一站式：plan + dashboard + 导出字段。"""
    plan = plan_paths(registry, profile=profile, task=task, top_k=3)
    dash = to_dashboard(plan)
    plan["dashboard"] = dash
    plan["prefer_local"] = bool((task or {}).get("prefer_local", False))
    return plan

