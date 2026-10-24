# -*- coding: utf-8 -*-
"""capability_runner：把“能力模块”从 ComfyUI 中剥离，形成独立 runnable 层。

目标：
- 成品不是 ComfyUI workflow，而是 8 个环节各自可独立运行、可组合、可审计的能力模块。
- ComfyUI 只是 image/video 的其中一个后端 adapter。
- 每个能力都带资源门禁、质量门禁、执行决策、执行结果。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

@dataclass
class Capability:
    id: str
    kind: str
    prompt: Optional[str] = None
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    resource_gate: Dict[str, Any] = field(default_factory=dict)
    quality_gate: Dict[str, Any] = field(default_factory=dict)

@dataclass
class CapabilityResult:
    ok: bool
    capability_id: str
    backend: str
    decision: Dict[str, Any]
    outputs: Dict[str, Any]
    gate: Dict[str, Any]
    error: Optional[str] = None

def workflow_to_capabilities(workflow: Dict[str, Any]) -> List[Capability]:
    """从 workflow 生成可独立运行的能力清单（不依赖 ComfyUI 也能执行）。"""
    caps: List[Capability] = []
    for nd in workflow.get("nodes", []):
        nid = nd.get("id")
        if not nid:
            continue
        kind = "text"
        if nid in {"character_image"}:
            kind = "image"
        elif nid in {"video_shot", "fx_enhance"}:
            kind = "video"
        elif nid in {"music", "voice", "bgm", "bgm_audio"}:
            kind = "audio"
        primary = nd.get("primary", {})
        caps.append(Capability(
            id=nid,
            kind=kind,
            prompt=(primary.get("params") or {}).get("prompt_prefix") or (primary.get("params") or {}).get("lora"),
            inputs={"primary": primary, "fallback_chain": nd.get("fallback_chain")},
            resource_gate={"estimated_vram_need_gb": primary.get("estimated_vram_need_gb")},
            quality_gate={"style": workflow.get("style"), "tier": workflow.get("tier")},
        ))
    return caps

def choose_backend(cap: Capability, profile: Dict[str, Any],
                   available_backends: Dict[str, Any]) -> Dict[str, Any]:
    """资源感知 + 能力类型匹配，选择后端。"""
    free_vram = float((profile.get("gpu") or {}).get("vram_gb") or 0)
    need = float(cap.resource_gate.get("estimated_vram_need_gb") or 0)
    resource_ok = True
    if free_vram > 0 and need > 0:
        resource_ok = need <= free_vram

    candidates = []
    for name, spec in available_backends.items():
        if spec.get("kind") not in {"*", cap.kind}:
            continue
        if not resource_ok and spec.get("cloud", False) is False:
            continue
        score = float(spec.get("score") or (2 if spec.get("cloud") else 1))
        candidates.append({"name": name, "score": score, "spec": spec})
    candidates.sort(key=lambda x: (-x["score"], x["name"]))
    top = candidates[0] if candidates else {"name": "mock", "score": 0.0, "spec": {"mock": True}}
    reason = "resource_ok" if resource_ok else "resource_fallback_to_cloud_or_mock"
    return {"backend": top["name"], "score": top["score"], "reason": reason,
            "resource_ok": resource_ok}

def run_capability(cap: Capability, profile: Dict[str, Any],
                   backends: Dict[str, Callable[..., Dict[str, Any]]]) -> CapabilityResult:
    """运行单个能力：决策→后端执行→质量/资源门禁→结果封装。"""
    available = {k: {"kind": "image" if k in {"comfyui","generic_local","local_video"} else
                       ("video" if k in {"cloud_video","comfyui"} else
                        ("audio" if k in {"cloud_audio","generic_audio"} else
                         ("text" if k in {"generic_text","cloud_text"} else "*"))),
                     "cloud": k.startswith("cloud"),
                     "score": 1.0} for k in backends}
    decision = choose_backend(cap, profile, available)
    runner = backends.get(decision["backend"])
    if runner is None:
        return CapabilityResult(ok=False, capability_id=cap.id, backend=decision["backend"],
                                decision=decision, outputs={}, gate={"error": "backend_missing"},
                                error="backend_missing")
    try:
        out = runner(cap, profile) or {}
    except Exception as e:
        return CapabilityResult(ok=False, capability_id=cap.id, backend=decision["backend"],
                                decision=decision, outputs={}, gate={"error": str(e)},
                                error=str(e))
    ok = bool(out.get("ok", True))
    gate = {
        "resource_ok": decision["resource_ok"],
        "quality_ok": bool(out.get("quality_ok", ok)),
        "backend": decision["backend"],
    }
    return CapabilityResult(ok=ok, capability_id=cap.id, backend=decision["backend"],
                            decision=decision, outputs=out, gate=gate,
                            error=None if ok else "capability_failed")

def run_capabilities(caps: List[Capability], profile: Dict[str, Any],
                     backends: Dict[str, Callable[..., Dict[str, Any]]]) -> Dict[str, Any]:
    results = [run_capability(c, profile, backends) for c in caps]
    failed = [r.capability_id for r in results if not r.ok]
    return {
        "ok": not failed,
        "completed": [r.capability_id for r in results if r.ok],
        "failed": failed,
        "results": [
            {"capability": r.capability_id, "ok": r.ok, "backend": r.backend,
             "decision": r.decision, "outputs": r.outputs, "gate": r.gate,
             "error": r.error} for r in results
        ],
    }

def default_local_backends(profile: Dict[str, Any]) -> Dict[str, Callable[..., Dict[str, Any]]]:
    """最小本地 runnable 后端：保证 8 环节在脱离 ComfyUI 时也能独立产出结构。"""
    def _noop(kind: str) -> Callable[..., Dict[str, Any]]:
        def _run(cap: Capability, prof: Dict[str, Any]) -> Dict[str, Any]:
            return {"ok": True, "kind": kind, "artifact": f"{cap.id}.payload.json"}
        return _run
    return {
        "generic_local": _noop(cap_kind_hint="generic"),
        "mock": _noop("mock"),
    }

def make_default_backends(workdir: str = "./_capability") -> Dict[str, Callable[..., Dict[str, Any]]]:
    """生成可落盘的默认后端（最小实现，后续替换成真实模型调用）。"""
    import json, os
    os.makedirs(workdir, exist_ok=True)
    def _local(cap: Capability, profile: Dict[str, Any]) -> Dict[str, Any]:
        out = os.path.join(workdir, f"{cap.id}.json")
        payload = {"capability": cap.id, "kind": cap.kind,
                   "prompt": cap.prompt, "inputs": cap.inputs,
                   "tier": cap.quality_gate.get("tier")}
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return {"ok": True, "path": out, "kind": cap.kind}
    return {"generic_local": _local, "mock": _local}
