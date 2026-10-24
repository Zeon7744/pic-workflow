# -*- coding: utf-8 -*-
"""model_registry：多模型统一注册表。

目标：
- 把 matrix.yaml / 自定义模型统一成一套可注册、可评分、可排序的后端资产
- 为 model_gateway 提供成本/速度/质量/资源四维输入
- ComfyUI 保持为 adapter 之一，不再作为主体
"""
from typing import Any, Dict, List, Optional

_KIND_ALIASES = {
    "sdxl": "image", "sd15": "image", "sd": "image", "flux": "image",
    "wan": "video", "kling": "video", "runway": "video", "ltx": "video",
    "cloud_kling": "video", "cloud_api_seedream": "image",
}


def _infer_kind(impl: str) -> str:
    s = str(impl or "")
    for key, kind in _KIND_ALIASES.items():
        if key in s:
            return kind
    if any(x in s for x in ["tts", "voice", "music", "bgm", "audio"]):
        return "audio"
    if any(x in s for x in ["llm", "gpt", "claude", "gemini"]):
        return "text"
    return "generic"


def _infer_cloud(impl: str) -> bool:
    s = str(impl or "").lower()
    return ("cloud" in s or "api" in s or "kling" in s
            or "runway" in s or "seedream" in s)


def _base_spec(impl: str, kind: str, source: str = "matrix",
               style_refs: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "id": impl,
        "kind": kind,
        "cloud": _infer_cloud(impl),
        "source": source,
        "style_refs": style_refs or [],
        "cost": 1.0,
        "speed": 1.0,
        "quality": 0.8,
        "min_vram_gb": 4.0 if not _infer_cloud(impl) else 0.0,
        "notes": [],
    }


def register_from_matrix(matrix: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """从 matrix.style_tracks 提取 image/video 模型资产，生成 registry。"""
    out: Dict[str, Dict[str, Any]] = {}
    for style_key, st in (matrix.get("style_tracks") or {}).items():
        for impl in st.get("image_model", []):
            spec = out.setdefault(impl, _base_spec(impl, _infer_kind(impl), "matrix", []))
            if style_key not in spec["style_refs"]:
                spec["style_refs"].append(style_key)
            spec["kind"] = "image"
        for impl in st.get("video_model", []):
            spec = out.setdefault(impl, _base_spec(impl, _infer_kind(impl), "matrix", []))
            if style_key not in spec["style_refs"]:
                spec["style_refs"].append(style_key)
            spec["kind"] = "video"
    return out


def add_custom_model(registry: Dict[str, Dict[str, Any]],
                     impl: str,
                     kind: str = "image",
                     cloud: bool = False,
                     cost: float = 1.0,
                     speed: float = 1.0,
                     quality: float = 0.8,
                     min_vram_gb: float = 4.0,
                     notes: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """补充注册自定义模型（如 Seedance/Kling/Runway/本地推理）。"""
    spec = _base_spec(impl, kind, "custom", [])
    spec.update({
        "cloud": cloud,
        "cost": cost,
        "speed": speed,
        "quality": quality,
        "min_vram_gb": min_vram_gb,
        "notes": notes or [],
    })
    registry[impl] = spec
    return registry


def score_backend(spec: Dict[str, Any],
                  profile: Dict[str, Any] = None,
                  strategy: Dict[str, Any] = None) -> Dict[str, Any]:
    """四维评分：资源、成本、速度、质量。"""
    profile = profile or {}
    strategy = strategy or {"cost_w": 0.25, "speed_w": 0.25, "quality_w": 0.5}
    free_vram = float((profile.get("gpu") or {}).get("vram_gb") or 0)
    need = float(spec.get("min_vram_gb") or 0)
    resource_ok = True
    resource_penalty = 0.0
    if free_vram > 0 and need > 0:
        resource_ok = need <= free_vram
        if not resource_ok:
            resource_penalty = 1.2

    quality = float(spec.get("quality") or 0.0)
    cost = max(0.2, float(spec.get("cost") or 1.0))
    speed = float(spec.get("speed") or 1.0)

    score = (
        strategy.get("quality_w", 0.5) * quality
        + strategy.get("cost_w", 0.25) * (1.0 / cost)
        + strategy.get("speed_w", 0.25) * speed
        - resource_penalty
    )
    if spec.get("cloud") and not resource_ok:
        score += 0.1
    return {
        "id": spec.get("id"),
        "kind": spec.get("kind"),
        "cloud": bool(spec.get("cloud")),
        "score": round(score, 4),
        "resource_ok": resource_ok,
        "cost": cost,
        "speed": speed,
        "quality": quality,
        "strategy": strategy,
    }


def rank_backends(registry: Dict[str, Dict[str, Any]],
                  profile: Dict[str, Any] = None,
                  kind: Optional[str] = None,
                  strategy: Dict[str, Any] = None,
                  top_k: int = 5) -> List[Dict[str, Any]]:
    """按策略输出 top_k 模型候选。"""
    rows = []
    for spec in registry.values():
        if kind and spec.get("kind") not in {kind, "generic"}:
            continue
        rows.append(score_backend(spec, profile or {}, strategy))
    rows.sort(key=lambda x: (-x["score"], x["id"]))
    return rows[:top_k]
