# -*- coding: utf-8 -*-
"""adaptive：实机数据反哺——越跑越准、越亲民。

闭环：
  采集(record_metrics) → 历史聚类 → 回归/规则反哺 → 动态调 matrix.yaml
  → 下一台机器读新 matrix 时拿到"更准"的 fallback_chain 优先级和
    estimated_vram_need_gb → 低配跑挂的镜头自动迁云端/offload 量化。

核心：matrix.yaml 不再是写死参数，而是"被实机数据持续校准"的数据表。
"""
import json
import os
import re
import statistics
from collections import defaultdict
from typing import Any, Dict, List

import yaml

MATRIX_REL = os.path.join("config", "matrix.yaml")
SNAPSHOT_REL = os.path.join("config", "matrix.adaptive.yaml")


# ---------------------------------------------------------------------------
# 1. 读历史，按 "档位 × 节点 × 模型实现" 聚类
# ---------------------------------------------------------------------------
def cluster_history(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 (tier, node_id, model_impl) 分桶。"""
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        key = f"{r.get('tier','?')}::{r.get('node_id','?')}::{r.get('model_impl','?')}"
        buckets[key].append(r)
    return dict(buckets)


def _mean(vals: List[float]) -> float:
    vals = [v for v in vals if isinstance(v, (int, float)) and v is not None and v > 0]
    return round(statistics.mean(vals), 2) if vals else None


# ---------------------------------------------------------------------------
# 2. 反哺规则：把"同档位同模型"的实际分布喂回 matrix
# ---------------------------------------------------------------------------
VRAM_HEADROOM = 1.15   # 实测峰值 * 1.15 余量 → 新 estimated_vram_need_gb
OOM_MIGRATE = True     # 低配跑挂自动往云端/offload 迁
MIN_SAMPLES = 2        # 至少 2 条实机数据才反哺，避免单点抖动


def advise_for_cell(cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    """对一个 (tier,node,model) 桶，产出反哺建议。

    返回:
      est_vram      建议的 estimated_vram_need_gb（实测峰值*余量）
      p95_elapsed   单镜头耗时 P95（资源消耗计量用）
      oom_rate      OOM 占比
      oom_degraded  该桶是否跑挂过
      recommend_migrate  是否建议迁云端/offload（亲民化核心）
      new_priority   迁移后的 fallback 目标（cloud/offload 实现名）
    """
    vrams = [r["peak_vram_gb"] for r in cells if r.get("peak_vram_gb")]
    elaps = [r["shot_elapsed_s"] for r in cells
             if r.get("shot_elapsed_s") is not None]
    oom = [r for r in cells if r.get("oom_degraded")]
    oom_rate = round(len(oom) / len(cells), 3) if cells else 0.0
    est_vram = round(max(vrams) * VRAM_HEADROOM, 2) if vrams else None

    # 亲民化：低配跑挂(oom) 或 耗时超阈值 → 建议迁云端/offload 量化
    slow = False
    if elaps:
        elaps_sorted = sorted(elaps)
        p95 = elaps_sorted[min(len(elaps_sorted) - 1, int(0.95 * len(elaps_sorted)))]
        slow = p95 > 120.0  # 单镜头 >120s 视为太慢，低配应让云端兜底
    recommend_migrate = OOM_MIGRATE and (oom_rate > 0.0 or slow)

    return {
        "samples": len(cells),
        "est_vram": est_vram,
        "mean_vram": _mean(vrams),
        "p95_elapsed": round(statistics.mean(elaps), 1) if elaps else None,
        "oom_rate": oom_rate,
        "recommend_migrate": recommend_migrate,
        "migrate_reason": "oom" if oom_rate > 0 else ("slow" if slow else "none"),
    }


# ---------------------------------------------------------------------------
# 3. 把建议写回 matrix.yaml（动态调 fallback_chain 优先级 + est_vram）
# ---------------------------------------------------------------------------
def _impl_class(impl: str) -> str:
    """判断实现属于哪类：cloud / gguf_offload / local_fp16 / local。"""
    s = (impl or "").lower()
    if any(k in s for k in ["cloud", "kling", "seedream", "grok", "api"]):
        return "cloud"
    if "gguf" in s or "offload" in s:
        return "gguf_offload"
    if "fp16" in s or "full" in s or "lora" in s:
        return "local_heavy"
    return "local"


def apply_advice_to_matrix(matrix: Dict[str, Any],
                           advice: Dict[str, Any]) -> Dict[str, Any]:
    """按建议改写 matrix（深拷贝，不污染原 dict）。

    改写两类字段：
      a) 每个实现节点的 estimated_vram_need_gb → 用实测 est_vram 覆盖
      b) fallback_chain 优先级重排：recommend_migrate 的桶把
         cloud / gguf_offload 类实现提到链首（低配优先安全档）
    """
    import copy
    m = copy.deepcopy(matrix)
    nodes = m.get("nodes", [])

    for key, adv in advice.items():
        if adv.get("samples", 0) < MIN_SAMPLES:
            continue
        tier, node_id, model_impl = key.split("::")
        node = next((n for n in nodes if n.get("id") == node_id), None)
        if not node:
            continue
        chain = node.get("fallback_chain", {}).get(tier)
        if not chain:
            continue

        # a) 覆盖 est_vram（找到对应 model_impl 的那一级）
        if adv.get("est_vram") is not None:
            for impl in chain:
                if impl.get("impl") == model_impl:
                    impl["estimated_vram_need_gb"] = adv["est_vram"]
                    impl["est_vram_source"] = "adaptive_history"  # 标记是实机反哺

        # b) 亲民化迁移：该桶实机跑挂(recommend_migrate) → 把跑挂的本地实现
        #    降级到链尾，云端兜底提到链首；未挂的安全本地(gguf)保持其次。
        if adv.get("recommend_migrate"):
            failing = model_impl
            cloud = [i for i in chain if _impl_class(i.get("impl")) == "cloud"]
            safe_local = [i for i in chain
                          if _impl_class(i.get("impl")) == "gguf_offload"
                          and i.get("impl") != failing]
            other = [i for i in chain
                     if _impl_class(i.get("impl")) not in ("cloud", "gguf_offload")
                     or i.get("impl") == failing]
            chain.clear()
            chain.extend(cloud + safe_local + other)
            node.setdefault("_adaptive", {})[f"{tier}"] = {
                "migrate": True, "reason": adv.get("migrate_reason"),
                "demoted": failing, "ts": "applied"}

    # 顶部加亲民化默认策略标记（供 workflow_gen 读）
    m.setdefault("default_policy", {})
    m["default_policy"]["philosophy"] = "低配优先跑通率，不追峰值画质"
    m["default_policy"]["low_tiers_prefer"] = ["gguf_q4_offload", "cloud_fallback"]
    m["default_policy"]["unlock_higher_at"] = "T2+"   # 高端机才解锁 720P/高量化
    return m


# ---------------------------------------------------------------------------
# 4. 反哺前后 档位推荐对比（交付要的核心示例）
# ---------------------------------------------------------------------------
def tier_recommend_before_after(matrix: Dict[str, Any],
                                advice: Dict[str, Any]) -> List[Dict[str, Any]]:
    """对每个被反哺的 (tier,node) 给出反哺前/后 的 primary 实现对比。

    before = 原 matrix 链首；after = apply_advice_to_matrix 改写后的链首。
    """
    import copy
    out = []
    applied = apply_advice_to_matrix(copy.deepcopy(matrix), advice)
    applied_nodes = {n.get("id"): n for n in applied.get("nodes", [])}
    orig_nodes = {n.get("id"): n for n in matrix.get("nodes", [])}
    for key, adv in advice.items():
        if adv.get("samples", 0) < MIN_SAMPLES:
            continue
        tier, node_id, model_impl = key.split("::")
        o_chain = orig_nodes.get(node_id, {}).get("fallback_chain", {}).get(tier, [])
        a_chain = applied_nodes.get(node_id, {}).get("fallback_chain", {}).get(tier, [])
        before = o_chain[0].get("impl") if o_chain else None
        after = a_chain[0].get("impl") if a_chain else before
        out.append({
            "tier": tier, "node": node_id,
            "before_primary": before, "after_primary": after,
            "migrated": adv.get("recommend_migrate", False) and (after != before),
            "reason": adv.get("migrate_reason", "none"),
            "est_vram_after": adv.get("est_vram"),
            "oom_rate": adv.get("oom_rate"),
        })
    return out


# ---------------------------------------------------------------------------
# 5. 一键闭环：读历史 → 产出建议 → 写 matrix.adaptive.yaml
# ---------------------------------------------------------------------------
def run_feedback(workdir: str,
                 matrix_path: str,
                 adaptive_out_path: str) -> Dict[str, Any]:
    """执行一次反哺。返回 {advice, before_after, applied}。"""
    from .record_metrics import load_history
    rows = load_history(workdir)
    buckets = cluster_history(rows)
    advice = {k: advise_for_cell(v) for k, v in buckets.items()}
    with open(matrix_path, encoding="utf-8") as f:
        matrix = yaml.safe_load(f)
    new_matrix = apply_advice_to_matrix(matrix, advice)
    # 写自适应后的 matrix（不覆盖原始 matrix.yaml，供对照 + 回滚）
    with open(adaptive_out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(new_matrix, f, allow_unicode=True, sort_keys=False)
    return {
        "samples_total": len(rows),
        "cells": len(buckets),
        "advice": advice,
        "before_after": tier_recommend_before_after(matrix, advice),
        "applied": True,
        "adaptive_matrix": adaptive_out_path,
    }


# ---------------------------------------------------------------------------
# 轻量回归（可选）：用 (vram,ram,arch) → tier 的线性回归校正打分
# ---------------------------------------------------------------------------
def fit_tier_offset(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """可选：从"OOM 占比"估每档的显存保守偏移（喂回 tier_scoring）。

    某档 OOM 率高 → 该档实际能跑的 vram 比标称低，返回该档保守偏移。
    返回 {T1: -1.0, T2: 0.5, ...}（GB，正=可放宽，负=需保守）。
    """
    per_tier: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        per_tier[r.get("tier", "?")].append(r)
    offsets: Dict[str, float] = {}
    for tier, cells in per_tier.items():
        if not cells:
            continue
        oom_rate = sum(1 for c in cells if c.get("oom_degraded")) / len(cells)
        # OOM 率 >20% → 扣 1GB；>40% → 扣 2GB（保守化）
        if oom_rate > 0.40:
            offsets[tier] = -2.0
        elif oom_rate > 0.20:
            offsets[tier] = -1.0
        else:
            offsets[tier] = 0.0
    return offsets
