# -*- coding: utf-8 -*-
"""observability：SLA/成功率/耗时/成本 指标 + 交付健康报告（行业前3的"可用度"维度）。

引擎"能不能稳定交付"需要可观测。本模块吃 record_metrics 的历史 + 出片日志，
产出四类信号，喂运营/白皇判断引擎当前健康度：

1. collect_metrics(history, runs) -> 聚合指标（成功率/中位耗时/OOM率/成本/发布率）
2. sla_report(metrics, sla) -> SLA 达成（成功率>=X / 耗时<=Y / 成本<=Z）逐条判定
3. cost_report(metrics) -> 成本口径（单集成本/单镜成本，对齐 resource_profiler 基线）
4. health_score(metrics) -> 0-100 交付健康分 + 红绿灯（绿可放量 / 黄限流 / 红停跑）

设计：纯离线聚合，吃 JSONL 历史；和 resource_profiler（对标 4 参照物）不同，
本模块聚焦"引擎自身跑得好不好"，是引擎做长期出品的运营基座。
"""
from typing import Dict, List, Any, Optional

# 出片成本基线（对齐 resource_profiler，元/镜 粗估）
_COST_PER_SHOT_EST = 0.5


def collect_metrics(history: List[Dict[str, Any]], runs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """聚合实跑指标。

    history: record_metrics 行（含 oom_degraded/peak_vram_gb/shot_elapsed_s）。
    runs: 出片 run（含 ok/publish_ready/elapsed_s）。
    返回 {total_runs, success_rate, median_elapsed_s, oom_rate,
          publish_ready_rate, vram_peak_max, est_cost_yuan}。
    """
    n_runs = len(runs or [])
    total = max(n_runs, len(history), 1)
    success = sum(1 for r in (runs or []) if r.get("ok"))
    publish = sum(1 for r in (runs or []) if r.get("publish_ready"))
    oom = sum(1 for h in history if h.get("oom_degraded"))
    elapseds = [float(r.get("elapsed_s") or 0) for r in (runs or []) if r.get("elapsed_s")]
    elapseds.sort()
    median_s = elapseds[len(elapseds) // 2] if elapseds else 0.0
    vram_max = max((float(h.get("peak_vram_gb") or 0) for h in history), default=0.0)
    est_cost = round(len(elapseds) * _COST_PER_SHOT_EST, 2)
    return {
        "total_runs": n_runs, "success": success,
        "success_rate": round(success / n_runs, 3) if n_runs else 0.0,
        "publish_ready_rate": round(publish / n_runs, 3) if n_runs else 0.0,
        "median_elapsed_s": round(median_s, 2),
        "oom_rate": round(oom / total, 3),
        "vram_peak_max": round(vram_max, 2),
        "est_cost_yuan": est_cost,
        "n_metrics": len(history),
    }


def sla_report(metrics: Dict[str, Any],
               sla: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """SLA 达成判定。默认：成功率>=0.95 / OOM率<=0.05 / 中位耗时<=900s。"""
    s = {"success_rate_min": 0.95, "oom_rate_max": 0.05, "median_elapsed_max_s": 900.0}
    if sla:
        s.update(sla)
    checks = [
        {"dim": "success_rate", "value": metrics.get("success_rate", 0),
         "target": f">= {s['success_rate_min']}",
         "met": metrics.get("success_rate", 0) >= s["success_rate_min"]},
        {"dim": "oom_rate", "value": metrics.get("oom_rate", 0),
         "target": f"<= {s['oom_rate_max']}",
         "met": metrics.get("oom_rate", 0) <= s["oom_rate_max"]},
        {"dim": "median_elapsed_s", "value": metrics.get("median_elapsed_s", 0),
         "target": f"<= {s['median_elapsed_max_s']}",
         "met": metrics.get("median_elapsed_s", 0) <= s["median_elapsed_max_s"]},
    ]
    all_met = all(c["met"] for c in checks)
    return {"all_met": all_met, "checks": checks,
            "sla": s, "note": "全达成才进放量档（绿），任一不过限流（黄/红）"}


def cost_report(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """成本口径（单集/单镜）。"""
    runs = max(1, metrics.get("total_runs", 1))
    shots = max(1, int(metrics.get("est_shots", runs * 6)))
    cost = metrics.get("est_cost_yuan", 0.0)
    return {
        "per_run": round(cost / runs, 2),
        "per_shot": round(cost / shots, 3),
        "per_episode": round(cost / runs * 6 / 6, 2),  # 每 run 约 6 镜
        "note": "估算口径，实机 cost 需回填 record_metrics",
    }


def health_score(metrics: Dict[str, Any],
                 sla: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """0-100 交付健康分 + 红绿灯。

    权重：成功率 40 / OOM率 20 / 耗时 20 / 可发布率 20。
    灯：>=80 绿(放量) / 60-79 黄(限流) / <60 红(停跑人工介入)。
    """
    sr = metrics.get("success_rate", 0)
    oom = metrics.get("oom_rate", 1.0)
    pub = metrics.get("publish_ready_rate", 0)
    med = metrics.get("median_elapsed_s", 900.0)
    time_score = max(0.0, 1.0 - med / 900.0)  # 900s 以上记 0
    score = round((sr * 0.4 + (1 - min(oom, 1.0)) * 0.2 + pub * 0.2 + time_score * 0.2) * 100, 1)
    light = "green" if score >= 80 else ("yellow" if score >= 60 else "red")
    return {
        "score": score, "light": light,
        "advice": {"green": "可放量出片", "yellow": "限流 + 预降级 T1",
                   "red": "停自动出片，人工介入"}[light],
        "breakdown": {"success_rate": sr, "oom_rate": oom,
                      "publish_ready_rate": pub, "time_score": round(time_score, 3)},
        "sla": sla_report(metrics, sla),
    }
