# -*- coding: utf-8 -*-
"""compat_layer：兼容性矩阵 + 降级检测（行业前3的"兼容性"维度）。

引擎要在不同平台（Windows/macOS/Linux）+ 不同交付渠道（网页/App/小程序/云端）+
不同格式（mp4/mov/webm + 音频）+ 不同依赖版本上都能跑/都能交付。本模块做：

1. platform_matrix -> 平台/渠道/格式 兼容性矩阵（查表）
2. detect_env() -> 探测当前运行环境（OS/Python/关键库 + torch 有无）
3. compat_report(env, target) -> 给目标交付渠道出兼容性报告（能跑什么/要降级什么/不兼容项）
4. degrade_for_env(env) -> 按环境给"降档建议"（无 GPU 降 T0 / 缺 torch 走 mock / 缺 ffmpeg 走 PIL）

设计：纯查表 + 运行时探测，离线可算；和 hw_probe（硬件探测）互补，
本模块聚焦"交付侧兼容性"而非硬件档位。
"""
import os
import platform
import sys
from typing import Dict, List, Any, Optional

# 平台/渠道/格式 兼容性矩阵（查表源）
COMPAT_MATRIX: Dict[str, Any] = {
    "os": {
        "Windows": {"ffmpeg": "binary_or_choco", "py_min": "3.9", "note": "默认桌面端，测试基线"},
        "Darwin":  {"ffmpeg": "brew",           "py_min": "3.9", "note": "MPS 可用（Apple Silicon）"},
        "Linux":   {"ffmpeg": "apt_or_static",  "py_min": "3.9", "note": "云端主战场"},
    },
    "delivery": {
        "web_page":   {"formats": ["mp4", "webm"], "codec": "h264", "max_mb": 200},
        "app_ios":    {"formats": ["mp4"],          "codec": "h264", "max_mb": 100},
        "app_android":{"formats": ["mp4", "webm"], "codec": "h264", "max_mb": 150},
        "miniapp":    {"formats": ["mp4"],          "codec": "h264", "max_mb": 30},
        "cloud":      {"formats": ["mp4", "mov", "webm"], "codec": "h264/hevc", "max_mb": 500},
    },
    "formats": {
        "mp4":  {"audio": ["aac", "mp3", "mpeg4"], "video": ["h264", "hevc"], "universal": True},
        "mov":  {"audio": ["aac", "pcm"],          "video": ["h264", "hevc", "prores"], "universal": False},
        "webm": {"audio": ["opus", "vorbis"],      "video": ["vp8", "vp9"],  "universal": False},
    },
    "deps": {
        "torch":    {"required": False, "fallback": "mock", "note": "无 torch 走 mock 出占位，可跑通链路"},
        "clip":     {"required": False, "fallback": "rule", "note": "无 CLIP 走规则质检"},
        "ffmpeg":   {"required": False, "fallback": "pil", "note": "无 ffmpeg 走 PIL 占位帧"},
        "flask":    {"required": True,  "fallback": None,   "note": "UI 必需"},
        "yaml":     {"required": True,  "fallback": None,   "note": "配置必需"},
    },
}


def _probe_optional(mod: str) -> bool:
    import importlib
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def detect_env() -> Dict[str, Any]:
    """探测当前运行环境，返回结构化 env dict。"""
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}"
    os_name = {"win32": "Windows", "darwin": "Darwin"}.get(platform.system().lower(), platform.system())
    has_torch = _probe_optional("torch")
    return {
        "os": os_name,
        "python": pyver,
        "cpu_count": os.cpu_count() or 1,
        "has_torch": has_torch,
        "has_ffmpeg": _probe_optional("shutil") and os.environ.get("HOOKFORGE_FFMPEG", "") != "none",
        "deps": {
            "flask": _probe_optional("flask"),
            "yaml": _probe_optional("yaml"),
            "torch": has_torch,
            "clip": has_torch and _probe_optional("clip"),
        },
        "platform_machine": platform.machine(),
    }


def compat_report(env: Dict[str, Any], target: str = "web_page") -> Dict[str, Any]:
    """给目标交付渠道出兼容性报告。

    返回 {supported, degrade:[...], incompatible:[...], note}。
    检查：OS 是否矩阵内 / 目标渠道格式是否 env 能产 / 关键依赖是否齐。
    """
    supported, degrade, incompatible = [], [], []
    os_entry = COMPAT_MATRIX["os"].get(env.get("os", ""))
    if os_entry is None:
        incompatible.append(f"未知 OS {env.get('os')}，矩阵未覆盖")
    deliv = COMPAT_MATRIX["delivery"].get(target)
    if deliv is None:
        incompatible.append(f"未知交付渠道 {target}")
        return {"supported": supported, "degrade": degrade,
                "incompatible": incompatible, "note": f"{target} 未定义"}

    # 渠道要求的最宽格式
    for fmt in deliv.get("formats", []):
        fmeta = COMPAT_MATRIX["formats"].get(fmt, {})
        if fmeta.get("universal"):
            supported.append(fmt)
        else:
            degrade.append(f"{fmt} 非全渠道通用，仅部分渠道可播")
    # 依赖缺失 -> 降级
    for dep, meta in COMPAT_MATRIX["deps"].items():
        if meta["required"] and not env.get("deps", {}).get(dep, False):
            incompatible.append(f"缺关键依赖 {dep}（无 fallback）")
        elif not meta["required"] and not env.get("deps", {}).get(dep, False):
            fb = meta.get("fallback")
            if fb:
                degrade.append(f"缺 {dep}，走 fallback={fb}")
    note = f"目标 {target}（max {deliv.get('max_mb')}MB, codec {deliv.get('codec')}）"
    return {"supported": supported, "degrade": degrade,
            "incompatible": incompatible, "note": note, "target": target}


def degrade_for_env(env: Dict[str, Any]) -> Dict[str, Any]:
    """按环境给降档建议。

    返回 {tier_hint, fallbacks:{dep:fallback}, reasons:[...]}。
    无 torch -> 全 mock 出片；无 ffmpeg -> PIL 占位；低核数 -> 降档。
    """
    reasons, fallbacks = [], {}
    tier_hint = "T2"
    if not env.get("has_torch"):
        fallbacks["torch"] = "mock"
        reasons.append("无 torch → 全链路 mock 出占位，链路可跑但不出真片")
        tier_hint = "T0"
    else:
        if env.get("cpu_count", 8) <= 4:
            reasons.append("核数 <=4，建议降 T1 保跑通率")
            tier_hint = "T1"
    for dep in ("ffmpeg", "clip"):
        if not env.get("deps", {}).get(dep):
            fb = COMPAT_MATRIX["deps"][dep]["fallback"]
            fallbacks[dep] = fb
            reasons.append(f"缺 {dep} → 走 {fb}")
    return {"tier_hint": tier_hint, "fallbacks": fallbacks, "reasons": reasons,
            "note": "按当前环境的最保守档位跑，不追峰值画质（对齐 default_policy 哲学）"}
