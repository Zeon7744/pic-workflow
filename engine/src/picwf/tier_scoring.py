# -*- coding: utf-8 -*-
"""档位匹配：显存 + 内存 + 架构修正 三维打分，输出 T0-T5。

打分规则（可被 config 覆盖）：
- 显存维：base_score = vram_gb
- 内存维：weight = 0.15 * ram_gb（封顶 6.0）
- 架构修正：Pascal -1.5（FP8 不可用，量化路线受限）；
            Turing  0.0；Ampere +1.0（FP8 可用）；Ada +1.5
- 总分 = 显存 + 内存维 + 架构修正
档位阈值：
  T0: score < 5.5   (纯云端)
  T1: 5.5 <= s < 9.5   (6-8GB)
  T2: 9.5 <= s < 14.5  (10-12GB)
  T3: 14.5<= s <19.5   (14-16GB)  [二期]
  T4: 19.5<= s <26.5   (20-24GB)  [二期]
  T5: s >= 26.5        (32GB+)    [二期]
MVP 只支持 T0/T1/T2，其他档位会被钳到最近的 MVP 档并标记 clamped。
"""
from typing import Any, Dict, List

TIER_THRESHOLDS = [
    ("T0", 0.0),
    ("T1", 6.0),       # <= 6GB 大致匹配（含架构修正）
    ("T2", 16.0),      # 6GB < score <= 16GB 大致匹配（含架构修正）
    ("T3", 20.0),      # 14-16GB
    ("T4", 26.0),      # 20-24GB
    ("T5", 32.0),      # 32GB+
]
# MVP_TIERS 保留用于向下兼容标记，但不再钳制档位匹配
# 二期已支持 T3/T4/T5，高端机可解锁 720P/1080P/LORA
MVP_TIERS = {"T0", "T1", "T2"}

ARCH_CORRECTION = {
    "Pascal": -1.5,
    "Turing": 0.0,
    "Ampere": 1.0,
    "Ada": 1.5,
    "Unknown": 0.0,
    "None": -3.0,  # 无 GPU
}


def compute_score(profile: Dict[str, Any]) -> Dict[str, Any]:
    gpu = profile.get("gpu", {})
    ram = profile.get("ram", {})
    vram = float(gpu.get("vram_gb", 0) or 0)
    ram_gb = float(ram.get("ram_gb", 0) or 0)
    arch = gpu.get("arch", "Unknown")

    vram_score = vram
    mem_score = min(6.0, 0.15 * ram_gb)
    arch_score = ARCH_CORRECTION.get(arch, 0.0)
    total = round(vram_score + mem_score + arch_score, 2)

    return {
        "vram_gb": vram, "ram_gb": ram_gb, "arch": arch,
        "vram_score": vram_score, "mem_score": round(mem_score, 2),
        "arch_correction": arch_score, "total": total,
        "fp8_support": bool(gpu.get("fp8_support", False)),
    }


def match_tier(profile: Dict[str, Any]) -> Dict[str, Any]:
    sc = compute_score(profile)
    total = sc["total"]
    # 取最高满足阈值的档位
    tier = "T0"
    for name, th in TIER_THRESHOLDS:
        if total >= th:
            tier = name
    # 二期已支持 T3/T4/T5，不再钳制
    clamped = False
    original = tier
    if tier not in MVP_TIERS:
        clamped = False  # T3/T4/T5 正式支持
    else:
        clamped = tier not in MVP_TIERS  # 仅用于标记是否经过钳制
    return {
        "tier": tier, "clamped": False, "mvp_supported": True,
        "score": sc,
    }


def clamp_mvp(tier: str) -> str:
    """非 MVP 档位钳到最近 MVP 档。"""
    return tier if tier in MVP_TIERS else "T2"


# ---------------------------------------------------------------------------
# CPU 算力修正（只用于本地 offload 路线的耗时预估，不影响档位 T0-T5）
# 档位由显存决定；CPU 快慢只影响"本地 gguf/offload 跑得多快"。
# ---------------------------------------------------------------------------
CPU_CORRECTION = {
    "low_u_series": 3.0,     # N95/N100 低功耗 U 级：本地 offload 耗时放大 3x
    "desktop_mid": 1.0,      # i5/Ryzen 5 桌面级：基准
    "desktop_high": 0.6,     # i7/i9 桌面级：offload 更快
    "workstation": 0.5,      # Xeon/Epyc
    "unknown": 1.0,
}

OFFLOAD_BASE_ELAPSED_S = 90.0  # 单镜头本地 gguf+offload 基准耗时（i5 桌面级）


def _cpu_class(cpu: Dict[str, Any]) -> str:
    if not cpu:
        return "unknown"
    model = str(cpu.get("model", "")).lower()
    ghz = float(cpu.get("ghz", 0) or 0)
    cores = int(cpu.get("cores", 0) or 0)
    if any(k in model for k in ("n95", "n100", "n200", "j4125")):
        return "low_u_series"
    if ghz and ghz <= 1.8 and cores and cores <= 6:
        return "low_u_series"
    if "xeon" in model or "epyc" in model:
        return "workstation"
    if ghz and ghz >= 4.0:
        return "desktop_high"
    if any(k in model for k in ("i7", "i9", "ryzen 7", "ryzen 9")):
        return "desktop_high"
    if any(k in model for k in ("i5", "ryzen 5")):
        return "desktop_mid"
    return "desktop_mid"


def estimate_offload_elapsed(profile: Dict[str, Any],
                             shots_per_ep: int = 10) -> Dict[str, Any]:
    """预估本地 offload 路线单集耗时（供 resource_profiler 实机回填对照）。

    档位/模型由 tier_scoring 决定，这里只算"这台 CPU 跑 offload 要多久"。
    N95（low_u_series）放大 3x → 本地 offload 慢，应优先云端；
    i7 桌面级（desktop_high）0.6x → 本地 offload 比基准快。
    """
    cpu_class = _cpu_class(profile.get("cpu", {}))
    factor = CPU_CORRECTION.get(cpu_class, 1.0)
    per_shot = round(OFFLOAD_BASE_ELAPSED_S * factor, 1)
    return {
        "cpu_class": cpu_class,
        "per_shot_s": per_shot,
        "ep_estimated_s": round(per_shot * shots_per_ep, 1),
        "ep_estimated_min": round(per_shot * shots_per_ep / 60.0, 1),
        "prefer_cloud": cpu_class in ("low_u_series", "unknown") and factor >= 2.0,
    }
