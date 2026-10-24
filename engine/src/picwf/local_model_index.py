# -*- coding: utf-8 -*-
"""local_model_index：把本机模型目录（如 ComfyUI checkpoints）纳入 registry。

设计目标：
- 不假设用户机器路径在云端可见，支持从本地扫描结果 / 目录路径 / 显式清单三种输入
- 输出与 model_registry 同构的 registry，可直接喂 efficiency_planner / model_gateway
- 做应用层智能：从文件名推断 kind、成本/速度/质量先验，并保留真实源目录信息

典型用法：
    from picwf.local_model_index import index_from_dir_listing
    reg = index_from_dir_listing(["sdxl_base.safetensors", "wan_14b.safetensors"])
"""
from typing import Any, Dict, List, Optional

_EXTS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf"}
_LOCAL_COST = 0.35
_LOCAL_SPEED = 1.0


def _infer_kind_from_name(name: str) -> str:
    s = (name or "").lower()
    if any(k in s for k in ["wan", "kling", "runway", "ltx", "video"]):
        return "video"
    if any(k in s for k in ["flux", "sdxl", "sd15", "stable_diffusion", "image"]):
        return "image"
    if any(k in s for k in ["tts", "voice", "music", "bgm", "audio"]):
        return "audio"
    return "image"


def _quality_prior(name: str, kind: str) -> float:
    """粗粒度先验质量分（后续可被 benchmark_advisory 回填替换）。"""
    s = (name or "").lower()
    base = 0.74 if kind == "image" else 0.78
    if any(k in s for k in ["flux", "sdxl"]):
        base += 0.04
    if any(k in s for k in ["wan", "14b", "gguf", "fp16"]):
        base += 0.03
    if "low" in s or "q4" in s or "lite" in s:
        base -= 0.04
    return round(min(0.98, max(0.45, base)), 3)


def _min_vram_prior(name: str, kind: str) -> float:
    s = (name or "").lower()
    if kind == "video":
        if "wan" in s and ("gguf" in s or "q4" in s):
            return 6.0
        if "wan" in s:
            return 10.0
        return 0.0
    if "sdxl" in s or "flux" in s:
        return 8.0
    if "sd15" in s or "stable_diffusion" in s:
        return 5.0
    return 4.0


def _normalize_model_id(name: str) -> str:
    s = (name or "").rsplit("/", 1)[-1]
    for ext in _EXTS:
        if s.lower().endswith(ext):
            s = s[: -len(ext)]
            break
    return s.strip()


def build_spec_from_local_file(name: str,
                               source_dir: str = "",
                               available_on_device: bool = True) -> Dict[str, Any]:
    model_id = _normalize_model_id(name)
    kind = _infer_kind_from_name(name)
    quality = _quality_prior(name, kind)
    min_vram = _min_vram_prior(name, kind)
    return {
        "id": model_id,
        "kind": kind,
        "cloud": False,
        "source": "local_model_index",
        "local_source_dir": source_dir,
        "local_file_name": name,
        "available_on_device": bool(available_on_device),
        "cost": 0.35,
        "speed": 1.0,
        "quality": quality,
        "min_vram_gb": min_vram,
        "notes": ["auto_indexed_from_local_dir"],
    }


def index_from_dir_listing(file_names: List[str],
                          source_dir: str = "",
                          include_unavailable: bool = True) -> Dict[str, Dict[str, Any]]:
    """从纯文件名列表构建 registry（适合无法直接枚举远程盘的场景）。"""
    reg: Dict[str, Dict[str, Any]] = {}
    for name in file_names or []:
        spec = build_spec_from_local_file(name, source_dir=source_dir,
                                          available_on_device=True)
        reg[spec["id"]] = spec
    if not include_unavailable:
        reg = {k: v for k, v in reg.items() if v.get("available_on_device")}
    return reg


def index_from_registry(registry: Dict[str, Dict[str, Any]],
                       local_model_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """把已有 registry 中属于本机模型的子集抽出来，便于本地优先策略使用。"""
    return {mid: registry[mid] for mid in local_model_ids if mid in registry}


def merge_into_registry(registry: Dict[str, Dict[str, Any]],
                        local_specs: Dict[str, Dict[str, Any]],
                        prefer_local: bool = True) -> Dict[str, Dict[str, Any]]:
    """把本地模型合入 registry；prefer_local=True 时本地同名条目覆盖远端默认。"""
    out = dict(registry)
    for mid, spec in (local_specs or {}).items():
        if prefer_local or mid not in out:
            merged = dict(out.get(mid, spec))
            merged.update(spec)
            out[mid] = merged
    return out


def build_registry_with_local(models_dir_listing: List[str],
                              source_dir: str = "",
                              base_registry: Optional[Dict[str, Dict[str, Any]]] = None,
                              prefer_local: bool = True) -> Dict[str, Dict[str, Any]]:
    """一站式：base_registry + 本地目录清单 → 合并后的 registry。"""
    base = base_registry or {}
    local_specs = index_from_dir_listing(models_dir_listing, source_dir=source_dir)
    return merge_into_registry(base, local_specs, prefer_local=prefer_local)



def scan_dir_listing(root_dir: str, refresh: bool = False) -> Dict[str, Any]:
    """扫描本机模型目录（如 D:\ComfyUI\...\checkpoints）。

    返回:
    {
      "root_dir": str,
      "files": [names],
      "registry": {...},
      "refreshed_at": 1700000000,
      "file_count": int,
    }

    refresh=True 时会重新读取目录并替换缓存（当前实现仍依赖 Python 文件系统；
    未来可接 inotify/Windows ReadDirectoryChangesW，这里先保留热更新入口）。
    """
    import os, time

    files: List[str] = []
    if os.path.isdir(root_dir):
        for name in sorted(os.listdir(root_dir)):
            full = os.path.join(root_dir, name)
            if os.path.isfile(full) and any(name.lower().endswith(ext) for ext in _EXTS):
                files.append(name)
    reg = index_from_dir_listing(files, source_dir=root_dir)
    return {
        "root_dir": root_dir,
        "files": files,
        "registry": reg,
        "refreshed_at": int(time.time()),
        "file_count": len(files),
        "refresh_supported": True,
    }


def build_hot_registry(base_registry: Dict[str, Dict[str, Any]],
                       root_dir: str = "",
                       prefer_local: bool = True,
                       manifest: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """热更新入口：优先读目录；无目录时回退 manifest。

    目标：新模型落盘后，刷新一次就能进入 registry，无需改代码。
    """
    if root_dir:
        scanned = scan_dir_listing(root_dir, refresh=True)
        files = scanned["files"]
    else:
        files = manifest or []
    return build_registry_with_local(
        files,
        source_dir=root_dir or "manifest",
        base_registry=base_registry or {},
        prefer_local=prefer_local,
    )


def registry_diff(previous: Dict[str, Dict[str, Any]],
                  current: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
    """比较两次 registry 的模型集合差异，用于热更新日志。"""
    prev_ids = set(previous.keys())
    cur_ids = set(current.keys())
    return {
        "added": sorted(cur_ids - prev_ids),
        "removed": sorted(prev_ids - cur_ids),
        "unchanged": sorted(prev_ids & cur_ids),
    }
