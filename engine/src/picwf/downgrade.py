# -*- coding: utf-8 -*-
"""动态降级：运行时显存 OOM 自动切 CPU offload → 量化 → 云端 API。

每个节点有「本地→量化→云端」三级预案。
降级决策基于：
1. 节点自身 fallback_chain（matrix.yaml 里每节点 3 级）
2. 运行时显存压力（free_vram_gb < 节点 estimated_vram_need * safety）
3. OOM 异常
"""
from typing import Any, Dict, List, Optional

SAFETY_FACTOR = 0.85  # 显存留 15% 余量


def pick_fallback(node_cfg: Dict[str, Any],
                  free_vram_gb: float,
                  oom_happened: bool = False) -> Dict[str, Any]:
    """根据节点配置 + 运行时状态，选出应该跑的下一级实现。

    返回 {level, impl_name, reason}
    level 0 = 本地原始, 1 = 量化/offload, 2 = 云端 API
    """
    chain = node_cfg.get("fallback_chain", [])
    if not chain:
        return {"level": 0, "impl_name": None, "reason": "no fallback_chain"}

    current_level = node_cfg.get("current_level", 0)
    est_need = float(node_cfg.get("estimated_vram_need_gb", 0.0) or 0.0)

    # OOM 直接跳一级
    if oom_happened:
        next_level = min(len(chain) - 1, current_level + 1)
        return {
            "level": next_level,
            "impl_name": chain[next_level].get("impl"),
            "reason": f"OOM -> level {next_level}",
        }

    # 显存不够 → 逐级上探
    for lv in range(current_level, len(chain)):
        est = chain[lv].get("estimated_vram_need_gb", 0.0)
        # 云端的 est=0（不占本地显存）
        if free_vram_gb >= est * SAFETY_FACTOR:
            return {"level": lv, "impl_name": chain[lv].get("impl"),
                    "reason": f"vram ok @ level {lv}"}
    # 全部不够 → 最高级（云端）
    last = len(chain) - 1
    return {"level": last, "impl_name": chain[last].get("impl"),
            "reason": "all local vram insufficient -> cloud"}


def build_degrade_plan(node_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """静态打印节点的全部三级预案。"""
    chain = node_cfg.get("fallback_chain", [])
    return {
        "node": node_cfg.get("id"),
        "primary": chain[0] if chain else None,
        "levels": [
            {"level": i, "impl": c.get("impl"),
             "vram_need": c.get("estimated_vram_need_gb", 0)}
            for i, c in enumerate(chain)
        ],
    }
