# -*- coding: utf-8 -*-
"""硬件探针核心逻辑：探测 GPU/显存/内存/架构/存储，输出结构化 profile。

Pascal(1060/1080/2080) 不支持 FP8，会被标记 fp8_support=False。
"""
import os
import platform
import re
import shutil
import subprocess
from typing import Any, Dict, Optional

# NVIDIA 型号 -> (架构, compute_cap, 是否支持 FP8)
ARCH_TABLE = {
    "1060": ("Pascal", "6.1", False),
    "1070": ("Pascal", "6.1", False),
    "1080": ("Pascal", "6.1", False),
    "1650": ("Turing", "7.5", False),
    "1660": ("Turing", "7.5", False),
    "2060": ("Turing", "7.5", False),
    "2070": ("Turing", "7.5", False),
    "2080": ("Turing", "7.5", False),
    "3060": ("Ampere", "8.6", True),
    "3070": ("Ampere", "8.6", True),
    "3080": ("Ampere", "8.6", True),
    "3090": ("Ampere", "8.6", True),
    "4060": ("Ada", "8.9", True),
    "4070": ("Ada", "8.9", True),
    "4080": ("Ada", "8.9", True),
    "4090": ("Ada", "8.9", True),
}


def _run(cmd, timeout=15):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout or ""
    except Exception:
        return ""


def _match_arch(model_num):
    """从型号数字匹配架构。"""
    if not model_num:
        return ("Unknown", None, False)
    for key, val in ARCH_TABLE.items():
        if key in model_num:
            return val
    return ("Unknown", None, False)


def detect_gpu() -> Dict[str, Any]:
    """探测 GPU。优先 nvidia-smi，失败标记 CPU-only。"""
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits"])
    if out:
        lines = [l for l in out.splitlines() if l.strip()]
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                name = parts[0]
                vram_gb = round(int(parts[1]) / 1024.0, 1)
                m = re.search(r"(\d{3,4})(Ti)?", name)
                model_num = (m.group(1) + (m.group(2) or "")) if m else ""
                arch, cc, fp8 = _match_arch(model_num)
                drv = parts[2] if len(parts) > 2 else None
                return {
                    "vendor": "NVIDIA", "has_gpu": True, "name": name,
                    "vram_gb": vram_gb, "arch": arch, "cc": cc,
                    "fp8_support": fp8, "driver_version": drv,
                }
    # AMD 探测
    amds = _run(["lspci"], timeout=8)
    if "nvidia" not in amds.lower() and "amd" in amds.lower():
        return {"vendor": "AMD", "has_gpu": True, "name": "AMD-GPU",
                "vram_gb": 0.0, "arch": "Unknown", "cc": None,
                "fp8_support": False, "driver_version": None}
    return {"vendor": "CPU-only", "has_gpu": False, "name": None,
            "vram_gb": 0.0, "arch": "None", "cc": None,
            "fp8_support": False, "driver_version": None}


def detect_memory() -> Dict[str, Any]:
    total_kb = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                    break
    except FileNotFoundError:
        pass
    return {"ram_gb": round(total_kb / 1024 / 1024, 1) if total_kb else 0.0}


def detect_storage() -> Dict[str, Any]:
    total = free = 0
    for src in ["/", os.environ.get("HOME", "/root")]:
        try:
            st = shutil.disk_usage(src)
            total += st.total
            free += st.free
        except Exception:
            pass
    out = _run(["lsblk", "-o", "NAME,TYPE,TRAN"], timeout=8)
    return {"free_gb": round(free / 1024 ** 3, 1),
            "total_gb": round(total / 1024 ** 3, 1),
            "is_nvme": "nvme" in out.lower()}


def build_profile() -> Dict[str, Any]:
    gpu = detect_gpu()
    return {
        "os": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "gpu": gpu,
        "ram": detect_memory(),
        "storage": detect_storage(),
        "cpu_count": os.cpu_count(),
    }


def pascal_launch_advice(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Pascal(1060/1070/1080, CC 6.1) 专属 ComfyUI 启动建议。

    2026-10-24 1060 实机踩坑结论固化：
    - Torch cu129/cu130 在 Pascal CC 6.1 报 "CUDA error: no kernel image is available"
    - 必须用 cu126 兼容版；启动注入 TORCH_CUDA_ARCH_LIST=6.1 / NVIDIA_TF32_OVERRIDE=0
    - 新版 ComfyUI 的 --cuda 与 --cuda-device/--cuda-malloc 歧义，不传
    - 整合包 checkpoints 为空时出图报 "model not in []"，需预放 SD1.5 底模
    """
    gpu = profile.get("gpu", {})
    arch = gpu.get("arch")
    cc = str(gpu.get("cc") or "")
    is_pascal = arch == "Pascal" or cc.startswith("6.1")
    drv = str(gpu.get("driver_version") or "")
    # 驱动支持的最高 CUDA（nvidia-smi 的 Driver Version 可粗推；这里给保守阈值）
    advice = {
        "is_pascal": is_pascal,
        "recommended_cuda": "cu126" if is_pascal else "cu126+",
        "forbidden_cuda": (["cu129", "cu130"] if is_pascal else []),
        "env": {
            "TORCH_CUDA_ARCH_LIST": "6.1" if is_pascal else "7.5+",
            "NVIDIA_TF32_OVERRIDE": "0" if is_pascal else "unset",
        },
        "drop_arg": ["--cuda"] if is_pascal else [],
        "require_base_model": "SD1.5 v1-5-pruned-emaonly.safetensors in models/checkpoints/",
        "kernel_selfcheck": "python -c \"import torch; print(torch.version.cuda, torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no-gpu')\"",
        "driver_version": drv,
        "notes": []
    }
    if is_pascal:
        advice["notes"].append(
            "Pascal CC 6.1 + cu129/cu130 会报 'no kernel image'；务必换 cu126 兼容版并注入上述 env")
    if drv and _drv_below(drv, "530"):
        advice["notes"].append(
            "驱动 %s 较老，建议升到 ≥530 以稳定支持 cu126" % drv)
    return advice


def _drv_below(drv: str, threshold: str) -> bool:
    """比较驱动主版本号是否低于阈值（取首段数字）。"""
    m = re.match(r"(\d+)", str(drv))
    m2 = re.match(r"(\d+)", threshold)
    if not m or not m2:
        return False
    return int(m.group(1)) < int(m2.group(1))


def kernel_selfcheck() -> Dict[str, Any]:
    """跑一条最小 CUDA kernel 调用，提前暴露 Pascal 'no kernel image' 问题。

    返回 {ok, cuda_version, device, error}。无 torch/GPU 时 ok=False 并给 reason。
    """
    out: Dict[str, Any] = {"ok": False, "cuda_version": None, "device": None, "error": None}
    try:
        import torch  # type: ignore
    except ImportError:
        out["error"] = "torch not installed"
        return out
    if not torch.cuda.is_available():
        out["error"] = "cuda not available (driver/GPU)"
        return out
    try:
        cc = torch.cuda.get_device_capability(0)
        out["cuda_version"] = torch.version.cuda
        out["device"] = torch.cuda.get_device_name(0)
        out["cc"] = f"{cc[0]}.{cc[1]}"
        # 触发一次真实 kernel：分配张量并做 matmul（Pascal 无 kernel 时这里会抛）
        a = torch.randn(4, 4, device="cuda")
        a @ a
        out["ok"] = True
        out["error"] = None
        return out
    except Exception as e:
        out["error"] = str(e)
        out["ok"] = False
        return out
