# -*- coding: utf-8 -*-
"""record_metrics：镜头跑完后采集实机指标，追加写进 state.json。

设计：
- orchestrator 每步落 state.json（done/failed/results）后，调本模块
  record_step() 追加 metrics 块（实机观测，不是预估）。
- shot_qa 质检后可调 record_qa() 把 4 维分 + 路由写回。
- 指标同时追加到 metrics_history.jsonl（按行，便于 adaptive.py 离线读、
  跨机器共享 state 时做聚类）。

采集字段（"每步落 state.json 时额外记录实机指标"）：
  peak_vram_gb     实际峰值显存（nvidia-smi 采样或 runner 上报；0=未知/云端）
  shot_elapsed_s   单镜头耗时
  quant_dtype      量化精度（gguf Q4_K_M / fp16 / cloud / cpu_offload ...）
  oom_degraded     是否触发 OOM 降级
  clip_4d          CLIP 四维分 {shape,style,place,intent}
  redo_queued      是否进 redo 队列（true/false/none）
  tier, node_id, model_impl  上下文标签
  ts               时间戳
  machine_hash     机器指纹（用于"同档位同模型"聚类 + 跨机共享）

字段即 adaptive.py 反哺的输入。
"""
import hashlib
import json
import os
import subprocess
import time
from typing import Any, Dict, Optional

STATE_FILE = "state.json"
HISTORY_FILE = "metrics_history.jsonl"


def machine_hash(profile: Dict[str, Any]) -> str:
    """机器指纹：gpu+ram+arch 的稳定 hash（同档同模型聚类的 key 之一）。"""
    gpu = profile.get("gpu", {})
    raw = json.dumps(
        {"vram": round(float(gpu.get("vram_gb", 0) or 0), 1),
         "arch": gpu.get("arch", "?"),
         "ram": profile.get("ram", {}).get("ram_gb", 0)},
        sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def sample_peak_vram_gb() -> float:
    """nvidia-smi 读当前显存占用（GB）。失败返回 0.0（云端/CPU 占位）。"""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        return round(float(out.splitlines()[0]) / 1024.0, 2)
    except Exception:
        return 0.0


def _append_history(workdir: str, rec: Dict[str, Any]):
    p = os.path.join(workdir, HISTORY_FILE)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def record_step(workdir: str,
                task_id: str,
                *,
                tier: str,
                node_id: str,
                model_impl: str,
                quant_dtype: str,
                oom_degraded: bool,
                redo_queued: bool,
                peak_vram_gb: Optional[float] = None,
                shot_elapsed_s: Optional[float] = None,
                profile: Optional[Dict[str, Any]] = None,
                clip_4d: Optional[Dict[str, float]] = None,
                ) -> Dict[str, Any]:
    """采集并落盘单步实机指标。

    - 追加到 workdir/state.json 的 metrics[task_id]（供 orchestrator 状态机读）
    - 追加一行到 workdir/metrics_history.jsonl（供 adaptive.py 离线聚类）
    返回该条指标 dict。
    """
    if peak_vram_gb is None:
        peak_vram_gb = sample_peak_vram_gb()
    rec = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task_id": task_id,
        "tier": tier,
        "node_id": node_id,
        "model_impl": model_impl,
        "quant_dtype": quant_dtype,
        "peak_vram_gb": peak_vram_gb,
        "shot_elapsed_s": round(shot_elapsed_s, 2) if shot_elapsed_s is not None else None,
        "oom_degraded": bool(oom_degraded),
        "redo_queued": bool(redo_queued),
        "clip_4d": clip_4d or {"shape": None, "style": None,
                                 "place": None, "intent": None},
        "machine_hash": machine_hash(profile) if profile else "unknown",
    }
    os.makedirs(workdir, exist_ok=True)

    # 写进 state.json（保留 orchestrator 的 done/failed/results）
    sp = os.path.join(workdir, STATE_FILE)
    state = {}
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as f:
            state = json.load(f)
    state.setdefault("metrics", {})
    state["metrics"][task_id] = rec
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    _append_history(workdir, rec)
    return rec


def record_qa(workdir: str, task_id: str, qa_report_dict: Dict[str, Any],
              *, tier: str, node_id: str, model_impl: str,
              quant_dtype: str, profile: Optional[Dict[str, Any]] = None,
              ) -> Dict[str, Any]:
    """把 shot_qa 的 QAReport.as_dict() 里的 4 维分 + 路由合并进指标。"""
    scores = qa_report_dict.get("scores", {})
    route = qa_report_dict.get("route", "pass")
    clip_4d = {
        "shape": scores.get("consistency_shape"),
        "style": scores.get("consistency_style"),
        "place": scores.get("continuity_place"),
        "intent": scores.get("alignment_intent"),
    }
    redo = route in ("redo_local", "cloud_refine")
    return record_step(
        workdir, task_id,
        tier=tier, node_id=node_id, model_impl=model_impl,
        quant_dtype=quant_dtype,
        oom_degraded=bool(qa_report_dict.get("oom_degraded", False)),
        redo_queued=redo,
        peak_vram_gb=qa_report_dict.get("peak_vram_gb"),
        shot_elapsed_s=qa_report_dict.get("shot_elapsed_s"),
        profile=profile,
        clip_4d=clip_4d,
    )


def load_history(workdir: str) -> list:
    """读取全部历史指标（adaptive.py 聚类用）。"""
    p = os.path.join(workdir, HISTORY_FILE)
    if not os.path.exists(p):
        return []
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
