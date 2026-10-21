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
    ("T1", 5.5),
    ("T2", 9.5),
    ("T3", 14.5),
    ("T4", 19.5),
    ("T5", 26.5),
]
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
    clamped = False
    original = tier
    if tier not in MVP_TIERS:
        # 钳到最近的 MVP 档：T3->T2, T4->T2, T5->T2（二期再扩）
        if tier in ("T3", "T4", "T5"):
            tier = "T2"
        clamped = True
    return {
        "tier": tier, "clamped": clamped, "mvp_supported": not clamped,
        "score": sc,
    }


def clamp_mvp(tier: str) -> str:
    """非 MVP 档位钳到最近 MVP 档。"""
    return tier if tier in MVP_TIERS else "T2"
