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


# ---------------------------------------------------------------------------
# 按失败类型路由：OOM / 超时 / 质量 三类各自降级策略不同
#   OOM    → 跳一级（显存压力，往量化/offload/云端走）
#   超时   → 同档换更快实现（量化/低分辨率/缩短步数），不一定要上云端
#   质量   → 保留高档位但收紧画质参数（不降显存，降质感）
# ---------------------------------------------------------------------------
FAILURE_TYPES = {"oom", "timeout", "quality"}


def _impl_class_local(impl: str) -> str:
    s2 = (impl or "").lower()
    if any(k in s2 for k in ["cloud", "kling", "seedream", "grok", "api"]):
        return "cloud"
    if "gguf" in s2 or "offload" in s2:
        return "gguf_offload"
    if "fp16" in s2 or "full" in s2 or "lora" in s2:
        return "local_heavy"
    return "local"


def route_fallback(node_cfg: Dict[str, Any],
                   free_vram_gb: float,
                   failure: str = "oom",
                   oom_happened: bool = False,
                   timeout_s: Optional[float] = None) -> Dict[str, Any]:
    """按失败类型选下一级实现。

    failure: "oom" / "timeout" / "quality"
      - oom     : 直接跳一级（同 pick_fallback 的 OOM 逻辑）
      - timeout : 在当前档内找"更快"实现（量化/云端），不跳显存档
      - quality : 保持当前实现，收紧 params（steps/res 降），不降级
    返回 {level, impl_name, reason, adjust}
    """
    chain = node_cfg.get("fallback_chain", [])
    if not chain:
        return {"level": 0, "impl_name": None, "reason": "no fallback_chain", "adjust": {}}
    current_level = node_cfg.get("current_level", 0)

    if failure == "quality":
        # 质量不达标：不换实现，收紧画质参数（steps 降 20%、分辨率降 1 档）
        adjust = {"steps_scale": 0.8, "res_step_down": 1, "keep_impl": True}
        return {"level": current_level,
                "impl_name": chain[current_level].get("impl"),
                "reason": "quality -> tighten params", "adjust": adjust}

    if failure == "timeout":
        # 超时：当前档内找更快实现——优先同档量化/offload，再考虑云端
        # 不跳显存档（可能只是 CPU 慢，量化更快）
        best_level, best_name = current_level, chain[current_level].get("impl")
        for lv in range(current_level, len(chain)):
            cls = _impl_class_local(chain[lv].get("impl"))
            if cls in ("gguf_offload", "cloud"):
                best_level, best_name = lv, chain[lv].get("impl")
                break
        return {"level": best_level, "impl_name": best_name,
                "reason": f"timeout -> faster impl @ level {best_level}",
                "adjust": {"timeout_s": timeout_s}}

    # 默认 oom：跳一级（保持向后兼容）
    next_level = min(len(chain) - 1, current_level + 1)
    return {"level": next_level, "impl_name": chain[next_level].get("impl"),
            "reason": f"OOM -> level {next_level}", "adjust": {}}


def build_degrade_plan_by_failure(node_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """按失败类型打印节点三级预案（供前端/日志展示）。"""
    plan = build_degrade_plan(node_cfg)
    plan["failure_routes"] = {
        "oom":     "跳一级（显存压力）",
        "timeout": "当前档换更快实现（量化/offload/云端）",
        "quality": "保留档位，收紧 steps/res 参数",
    }
    return plan
