# -*- coding: utf-8 -*-
"""model_gateway：统一模型接入层（本地/云/多模型，ComfyUI 只是 adapter 之一）。

目标：
- 不绑死 ComfyUI，按能力类型统一选择后端
- 支持 local/cloud/mock 三类
- 输出决策可解释：为什么选这个后端、资源是否满足、是否兜底
"""
from typing import Any, Dict, List, Optional

def _kind_of(name: str, spec: Dict[str, Any]) -> str:
    return str(spec.get("kind", "image"))

def available_backend_specs() -> Dict[str, Dict[str, Any]]:
    """当前可注册的后端能力清单（可扩展接 Seedance/Kling/Runway 等）。"""
    return {
        "comfyui": {"kind": "image", "cloud": False, "priority": 10, "note": "本地ComfyUI adapter"},
        "generic_local": {"kind": "*", "cloud": False, "priority": 20, "note": "通用本地后端占位"},
        "cloud_video": {"kind": "video", "cloud": True, "priority": 30, "note": "云端视频模型"},
        "cloud_audio": {"kind": "audio", "cloud": True, "priority": 30, "note": "云端音频模型"},
        "mock": {"kind": "*", "cloud": False, "priority": 90, "note": "离线mock"},
    }


def choose_backend(kind: str, profile: Dict[str, Any] = None,
                   backends: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """资源感知选择后端。

    kind: image/video/audio/text
    profile: 至少含 gpu.vram_gb 或 cpu.ram_gb
    返回 {backend, cloud, reason, resource_ok}
    """
    profile = profile or {}
    specs = backends or available_backend_specs()
    free_vram = float((profile.get("gpu") or {}).get("vram_gb") or 0)
    free_ram = float((profile.get("cpu") or {}).get("ram_gb") or 0)

    candidates: List[Dict[str, Any]] = []
    for name, spec in specs.items():
        if spec.get("kind") != kind and spec.get("kind") != "*":
            continue
        resource_ok = True
        if not spec.get("cloud") and kind in {"image", "video"} and free_vram > 0:
            need = float(spec.get("min_vram_gb", 6.0))
            resource_ok = free_vram >= need
        elif not spec.get("cloud") and kind == "audio" and free_ram > 0:
            need = float(spec.get("min_ram_gb", 2.0))
            resource_ok = free_ram >= need
        score = int(spec.get("priority", 100))
        if not resource_ok:
            score += 50  # 资源不足降低本地优先级
        candidates.append({"name": name, "spec": spec, "score": score,
                           "resource_ok": resource_ok})
    candidates.sort(key=lambda x: (x["score"], x["name"]))
    top = candidates[0] if candidates else {"name": "mock", "spec": {"kind": "*", "cloud": False},
                                            "score": 99, "resource_ok": True}
    reason = "resource_ok_local_first" if top["resource_ok"] else "fallback_cloud_or_mock"
    return {
        "backend": top["name"],
        "kind": kind,
        "cloud": bool(top["spec"].get("cloud", False)),
        "resource_ok": bool(top["resource_ok"]),
        "reason": reason,
    }


def gate_decision(decision: Dict[str, Any],
                  quality_score: Optional[float] = None,
                  quality_threshold: float = 0.8) -> Dict[str, Any]:
    """把“资源决策 + 质量门禁”合成一个可解释结果。"""
    ok = decision.get("resource_ok", True)
    quality_ok = True
    if quality_score is not None:
        quality_ok = quality_score >= quality_threshold
    return {
        "pass": bool(ok and quality_ok),
        "resource_ok": bool(ok),
        "quality_ok": bool(quality_ok),
        "quality_score": quality_score,
        "reason": "quality_gate_failed" if not quality_ok else decision.get("reason", ""),
    }
