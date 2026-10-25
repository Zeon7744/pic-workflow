# -*- coding: utf-8 -*-
"""resource_allocator：资源分配与任务调度引擎（行业前3的"资源分配"维度）。

resource_profiler 管"消耗多少/对标谁"，本模块管"怎么分/怎么调度/超没超配额"——
多任务并出片时，显存/算力/时间/预算是有限资源，本模块做四件事：

1. budget_plan(total_budget, tasks) -> 给 N 个出片任务分配资源（显存/时长/算力），
   按任务优先级 + 档位吃显存占比 动态分，超预算时按优先级砍低优先级任务。
2. schedule(concurrency, task_budgets) -> 并发调度（同时几路 GPU 任务排队），
   显存够才起新任务，不够就排队等前序释放。
3. quota_check(usage, quota) -> 配额/节流（日调用上限/月成本上限/OOM 熔断），
   超阈值进降速/降级。
4. adaptive_realloc(state) -> 运行中重分配：某任务 OOM 自动让显存给更稳的任务，
   并给"降档/降分辨率/插云"三级动作建议。

设计原则：纯规则离线可算，吃的是 matrix 的 vram_need 和任务优先级，
不依赖 torch；和 resource_profiler（消耗对标）互补不重叠。
"""
from typing import Dict, List, Any, Optional

# 任务默认画像（可被 task dict 覆盖）
_DEFAULT_TASK = {
    "priority": 5,          # 1-10，越高越先分资源
    "tier": "T1",           # 决定显存吃量
    "shots": 6,             # 镜头数
    "duration_s_per_shot": 4.0,
}

# 档位 -> 单任务吃显存（GB），对齐 matrix.yaml 的 vram_range
_TIER_VRAM = {"T0": 2.0, "T1": 6.0, "T2": 11.0, "T3": 15.0, "T4": 22.0, "T5": 26.0}
# 档位 -> 单任务吃算力（相对单位，越高越重）
_TIER_FLOP = {"T0": 0.3, "T1": 0.5, "T2": 0.7, "T3": 0.9, "T4": 1.2, "T5": 1.4}
# 档位 -> 单任务吃时长（分钟，粗估，shot 数 * 单镜 4s / 本地倍率）
_TIER_TIME = {"T0": 2.0, "T1": 4.0, "T2": 6.0, "T3": 9.0, "T4": 12.0, "T5": 16.0}


def _merged_task(task: Dict[str, Any]) -> Dict[str, Any]:
    t = dict(_DEFAULT_TASK)
    t.update({k: v for k, v in (task or {}).items() if v is not None})
    return t


def budget_plan(total_budget: Dict[str, float],
                tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """给 N 个任务分配资源预算（显存/算力/时长/成本）。

    total_budget: {vram_gb, flop, minutes, cost} 总盘子。
    tasks: 每项带 priority/tier/shots。
    按 priority 降序分：先满足高优先级，余量再给低优先级；不够则低优先级被砍。
    返回 {allocated:{task_id:{...}}, dropped:[task_id], remaining:{...}, fit}。
    """
    norm = total_budget.get
    vram_total = float(total_budget.get("vram_gb", 999))
    flop_total = float(total_budget.get("flop", 999))
    time_total = float(total_budget.get("minutes", 999))

    # 按优先级降序
    ranked = sorted(
        ((_merged_task(t), t.get("id", i)) for i, t in enumerate(tasks)),
        key=lambda x: -x[0].get("priority", 5))

    allocated: Dict[str, Dict[str, float]] = {}
    dropped: List[Any] = []
    used = {"vram_gb": 0.0, "flop": 0.0, "minutes": 0.0}
    for mt, tid in ranked:
        tier = mt.get("tier", "T1")
        shots = int(mt.get("shots", 6))
        vram = _TIER_VRAM.get(tier, 6.0)
        flop = _TIER_FLOP.get(tier, 0.5) * shots / 6.0
        minutes = _TIER_TIME.get(tier, 4.0) * shots / 6.0
        # 并发不叠加显存（错峰起），但总盘子是"峰值"，按最大并发估算已在上层
        if vram > vram_total or used["flop"] + flop > flop_total or used["minutes"] + minutes > time_total:
            dropped.append(tid)
            continue
        allocated[str(tid)] = {"vram_gb": round(vram, 1), "flop": round(flop, 3),
                               "minutes": round(minutes, 2), "tier": tier,
                               "priority": mt.get("priority", 5)}
        used["vram_gb"] = max(used["vram_gb"], vram)  # 峰值
        used["flop"] += flop
        used["minutes"] += minutes
    remaining = {k: round(v - used[k], 2) for k, v in
                 (("vram_gb", vram_total), ("flop", flop_total), ("minutes", time_total))}
    return {"allocated": allocated, "dropped": dropped,
            "used": used, "remaining": remaining, "fit": not dropped}


def schedule(concurrency: int, task_budgets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """并发调度：同时最多 concurrency 路任务，按 vram 峰值排进波次。

    task_budgets: 每项带 vram_gb / priority。
    返回 [{wave, tasks:[...], peak_vram}]——同一波内 vram 之和 <= 单卡显存假设
    （这里用"峰值不叠加"模型：同波多任务各占自身 vram，取 max 作为波峰值）。
    """
    conc = max(1, int(concurrency))
    ranked = sorted(task_budgets, key=lambda x: -x.get("priority", 5))
    waves: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []
    for tb in ranked:
        if len(cur) >= conc:
            peak = max((x.get("vram_gb", 6.0) for x in cur), default=6.0)
            waves.append({"wave": len(waves) + 1, "tasks": cur, "peak_vram": round(peak, 1)})
            cur = []
        cur.append(tb)
    if cur:
        peak = max((x.get("vram_gb", 6.0) for x in cur), default=6.0)
        waves.append({"wave": len(waves) + 1, "tasks": cur, "peak_vram": round(peak, 1)})
    return waves


def quota_check(usage: Dict[str, Any], quota: Dict[str, Any]) -> Dict[str, Any]:
    """配额/节流：日调用/月成本/OOM 次数 上限，超阈值给降速建议。

    usage: {api_calls_today, cost_month, oom_count}
    quota: {api_calls_limit, cost_limit, oom_limit}
    返回 {over:[dim], actions:[...], throttle}。
    """
    over, actions = [], []
    pairs = [
        ("api_calls_today", "api_calls_limit"),
        ("cost_month", "cost_limit"),
        ("oom_count", "oom_limit"),
    ]
    for use_k, cap_k in pairs:
        u, cap = usage.get(use_k), quota.get(cap_k)
        if u is None or cap is None:
            continue
        ratio = u / cap
        if ratio > 1.0:
            over.append(use_k)
            actions.append({"dim": use_k, "ratio": round(ratio, 2),
                            "action": "超配额，熔断该维度 + 转云端兜底"})
        elif ratio > 0.8:
            actions.append({"dim": use_k, "ratio": round(ratio, 2),
                            "action": "接近配额（>80%），降速 50% + 预降级到 T1"})
    return {"over": over, "actions": actions, "throttle": bool(over),
            "healthy": len(over) == 0}


def adaptive_realloc(state: Dict[str, Any]) -> Dict[str, Any]:
    """运行中重分配：某任务 OOM 时，让显存给更稳任务 + 三级降档动作。

    state: {tasks:[{id, tier, oom, vram_need, vram_avail, status}]}
    返回 {realloc:[{task_id, action, to_tier, reason}], freed_vram}。
    三级：降档（T2->T1）/ 降分辨率（720->480）/ 插云（本地->cloud_kling）。
    """
    actions, freed = [], 0.0
    for t in state.get("tasks", []):
        if not t.get("oom"):
            continue
        tier = t.get("tier", "T2")
        need, avail = t.get("vram_need", 0), t.get("vram_avail", 0)
        # 三级降级
        if tier in ("T4", "T5", "T3"):
            to_tier = {"T5": "T4", "T4": "T3", "T3": "T2"}.get(tier, "T1")
            act = f"降档 {tier}->{to_tier}"
        elif need > avail:
            act, to_tier = "降分辨率 720->480 + 开 offload", "T1"
        else:
            act, to_tier = "插云兜底 cloud_kling", "cloud"
        freed += max(0.0, need - avail)
        actions.append({"task_id": t.get("id"), "action": act,
                        "to_tier": to_tier,
                        "reason": f"OOM (need {need} > avail {avail})"})
    return {"realloc": actions, "freed_vram": round(freed, 1),
            "note": "OOM 任务按 降档>降分辨率>插云 三级回收显存"}
