# -*- coding: utf-8 -*-
"""workflow_explorer：引擎的「主动探索 + 工作流产出」能力。

定位（白皇 2026-10-25 强调）：ComfyUI 只是出品/测试数据渠道，
引擎自身价值是「工作流迭代 + 优化产出 + 超越 ComfyUI 的独立功能」。

本模块把 comfyui_feedback 的"被动学习"升级为"主动迭代"：
  1. next_exploration_plan
     基于 matrix.adaptive.yaml + 实跑历史，识别"哪些 (tier, node, model_impl)
     组合还没被验证过"，按"低 OOM 风险 + 本地可跑 + 优先级"打分排序，
     产出下一批该试的探索计划——引擎自己决定下一步探索什么，不是盲目遍历。
  2. emit_comfyui_workflow
     把一个探索组合渲染成"可直接 POST 给 ComfyUI /prompt 的真实 7 节点
     文生图工作流 JSON"。引擎产出可执行工作流，而非被动使用 ComfyUI。
  3. explore_full_cycle
     学习(learn_from_comfyui_runs) → 探索(next_exploration_plan) → 工作流
     产出(emit_comfyui_workflow) 的完整主动迭代闭环。
     ComfyUI 跑完一次，引擎不仅更聪明，还知道下一批该试什么、并直接
     生成可执行工作流喂回去——这是超越 ComfyUI 的核心独立功能。
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Set

# ---------------------------------------------------------------------------
# 真实 ComfyUI 7 节点文生图工作流模板（与 comfyui_runner._comfyui_exec 同源）
# ---------------------------------------------------------------------------
DEFAULT_CHECKPOINT = "v1-5-pruned-emaonly-fp16.safetensors"


def _workflow_template(checkpoint: str,
                       prompt: str,
                       negative_prompt: str,
                       width: int = 512,
                       height: int = 512,
                       steps: int = 20,
                       cfg: float = 7.0,
                       seed: int = 0) -> Dict[str, Any]:
    """渲染一份可直接 POST 给 ComfyUI /prompt 的真实文生图工作流。"""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "latent_image": ["4", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "hookforge", "images": ["6", 0]},
        },
    }


# ---------------------------------------------------------------------------
# 1. 主动探索计划：识别未验证组合 + 打分排序
# ---------------------------------------------------------------------------
def _tier_vram_cap(tier: str) -> float:
    """档位 → 可承受显存上限（GB）。与 hw_probe 的档位定义对齐。"""
    return {
        "T0": 0.0, "T1": 6.0, "T2": 10.0,
        "T3": 14.0, "T4": 22.0, "T5": 26.0,
    }.get(tier, 6.0)


def _impl_risk_class(impl: str) -> str:
    s = (impl or "").lower()
    if any(k in s for k in ("cloud", "kling", "seedream", "grok", "api")):
        return "cloud"
    if "gguf" in s or "offload" in s:
        return "gguf_offload"
    if "fp16" in s or "fa_" in s or "full" in s or "lora" in s:
        return "local_heavy"
    return "local"


def next_exploration_plan(adaptive_matrix: Dict[str, Any],
                          history: List[Dict[str, Any]],
                          tiers: Optional[List[str]] = None,
                          node_ids: Optional[List[str]] = None,
                          top_k: int = 5) -> List[Dict[str, Any]]:
    """基于 adaptive matrix + 实跑历史，产出下一批该试的探索组合清单。

    策略（引擎主动探索，非盲目遍历）：
      - 候选 = matrix 各 (tier, node) fallback_chain 里的全部 model_impl
      - 剔除 history 里已被同 scenario+node+impl 充分验证的（samples>=2 且 OOM 率低）
      - 打分 = 本地可跑优先 + 显存贴合档位 + OOM 风险低
      - 按分数降序取 top_k

    返回 [{tier, node, model_impl, risk, expected_vram, reason, untested}]
    """
    tiers = tiers or [t for t in ["T0", "T1", "T2", "T3", "T4", "T5"]
                      if t in (adaptive_matrix.get("tiers") or [])]
    if not tiers:
        tiers = ["T0", "T1", "T2"]

    # 已验证集合：(tier, node, impl) 且 samples>=2 且 oom_rate<=0.2
    verified: Set[str] = set()
    oom_by_key: Dict[str, float] = {}
    for r in history:
        k = f"{r.get('tier','?')}::{r.get('node_id','?')}::{r.get('model_impl','?')}"
        oom_by_key.setdefault(k, []).append(bool(r.get("oom_degraded")))
    for k, ooms in oom_by_key.items():
        if len(ooms) >= 2:
            rate = sum(ooms) / len(ooms)
            if rate <= 0.2:
                verified.add(k)

    # 候选：每个 (tier, node) 的 chain 里所有 impl
    candidates: List[Dict[str, Any]] = []
    nodes = adaptive_matrix.get("nodes", [])
    for node in nodes:
        nid = node.get("id")
        if node_ids and nid not in node_ids:
            continue
        fc = node.get("fallback_chain", {})
        for tier in tiers:
            chain = fc.get(tier) or []
            cap = _tier_vram_cap(tier)
            for impl in chain:
                impl_name = impl.get("impl")
                if not impl_name:
                    continue
                key = f"{tier}::{nid}::{impl_name}"
                untested = key not in verified
                est_vram = float(impl.get("estimated_vram_need_gb") or 0.0)
                rclass = _impl_risk_class(impl_name)
                # 打分：未验证加分、本地可跑加分、显存贴合档位加分、OOM 低加分
                score = 0.0
                reason_bits: List[str] = []
                if untested:
                    score += 3.0
                    reason_bits.append("未验证")
                if rclass == "gguf_offload":
                    score += 2.0
                    reason_bits.append("本地gguf安全")
                elif rclass == "cloud":
                    score += 0.5
                    reason_bits.append("云兜底")
                if est_vram and est_vram <= cap:
                    score += 1.5
                    reason_bits.append(f"显存{est_vram}≤档位{cap}")
                elif est_vram and est_vram > cap:
                    score -= 1.0
                    reason_bits.append(f"显存{est_vram}>档位{cap}(风险)")
                hist_oom = (sum(oom_by_key.get(key, [False])) /
                             max(1, len(oom_by_key.get(key, [False]))))
                if hist_oom == 0.0:
                    score += 1.0
                    reason_bits.append("历史OOM低")
                elif hist_oom > 0.3:
                    score -= 1.5
                    reason_bits.append(f"历史OOM{hist_oom:.2f}(高风险)")
                candidates.append({
                    "tier": tier, "node": nid, "model_impl": impl_name,
                    "risk": rclass, "expected_vram": est_vram,
                    "untested": untested, "score": round(score, 2),
                    "reason": "; ".join(reason_bits) or "默认",
                })

    candidates.sort(key=lambda c: (-c["score"], c["tier"], c["node"], c["model_impl"]))
    return candidates[:top_k]


# ---------------------------------------------------------------------------
# 2. 工作流产出：把探索组合渲染成可执行 ComfyUI 工作流
# ---------------------------------------------------------------------------
def emit_comfyui_workflow(plan_item: Dict[str, Any],
                          checkpoint: str = DEFAULT_CHECKPOINT,
                          prompt: str = "hookforge dark thriller short drama shot",
                          negative_prompt: str = "low quality, blurry, extra limbs",
                          width: int = 512, height: int = 512,
                          steps: int = 20, cfg: float = 7.0,
                          seed: int = 0) -> Dict[str, Any]:
    """把一个探索组合渲染成可直接喂 ComfyUI 的真实工作流 JSON。

    返回 {"plan_item": ..., "workflow": {...}, "payload_for_prompt_endpoint": {...}}
    """
    wf = _workflow_template(checkpoint, prompt, negative_prompt,
                            width, height, steps, cfg, seed)
    payload = {
        "prompt": wf,
        "model_impl": plan_item.get("model_impl"),
        "tier": plan_item.get("tier"),
        "node": plan_item.get("node"),
        "exploration_reason": plan_item.get("reason"),
        "expected_vram_gb": plan_item.get("expected_vram"),
    }
    return {"plan_item": plan_item, "workflow": wf,
            "payload_for_prompt_endpoint": payload}


def emit_exploration_batch(plan: List[Dict[str, Any]],
                           checkpoint: str = DEFAULT_CHECKPOINT,
                           prompts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """批量渲染：把探索计划里的每个组合都生成可执行工作流。"""
    prompts = prompts or []
    out = []
    for i, item in enumerate(plan):
        p = prompts[i] if i < len(prompts) else \
            f"hookforge exploration {item.get('tier')} {item.get('node')} {item.get('model_impl')}"
        out.append(emit_comfyui_workflow(item, checkpoint=checkpoint, prompt=p))
    return out


# ---------------------------------------------------------------------------
# 3. 主动迭代闭环：学习 → 探索 → 工作流产出
# ---------------------------------------------------------------------------
def explore_full_cycle(workdir: str,
                       matrix_path: str,
                       adaptive_out_path: str,
                       tiers: Optional[List[str]] = None,
                       node_ids: Optional[List[str]] = None,
                       top_k: int = 5,
                       checkpoint: str = DEFAULT_CHECKPOINT) -> Dict[str, Any]:
    """引擎主动迭代闭环：
      学习(读 history + 回流 matrix.adaptive.yaml)
      → 探索(next_exploration_plan 识别未验证组合)
      → 工作流产出(emit_exploration_batch 生成可执行 ComfyUI 工作流)

    返回 {learn: {...}, exploration: [...], workflows: N, ready_for_run: bool}
    """
    from .adaptive import run_feedback
    from .record_metrics import load_history

    learn = run_feedback(workdir, matrix_path, adaptive_out_path)
    history = load_history(workdir)
    # 用回流后的 adaptive matrix 做探索（学习结果影响下一轮探索决策）
    import yaml
    with open(adaptive_out_path, encoding="utf-8") as f:
        adaptive_matrix = yaml.safe_load(f)
    plan = next_exploration_plan(adaptive_matrix, history,
                                  tiers=tiers, node_ids=node_ids, top_k=top_k)
    batch = emit_exploration_batch(plan, checkpoint=checkpoint)
    return {
        "learn": learn,
        "exploration": plan,
        "workflows": len(batch),
        "workflows_payload": batch,
        "ready_for_run": bool(plan) and bool(batch),
        "note": ("引擎主动迭代完成：基于实跑数据回流矩阵，"
                 f"识别出 {len(plan)} 个待探索组合并生成可执行 ComfyUI 工作流，"
                 "下一步可直接 POST /prompt 跑新组合，形成持续超越的闭环"),
    }
