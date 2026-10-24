# -*- coding: utf-8 -*-
"""任务编排 + 断点重跑：失败镜头重做而非整集重跑。

每个镜头/节点是一个可断点任务。执行器记录 state.json（哪个镜头成功/失败），
重跑时只重做失败 + 未做的，成功的直接复用产物，避免整集重跑浪费资源。
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 可选挂钩：每步落盘后记录实机指标（adaptive 反哺的输入）
try:
    from . import record_metrics as _rm
except Exception:
    _rm = None

# 可选挂钩：失败路由 + 双维 combo 学习（接到主链路的闭环）
try:
    from . import downgrade as _dg
except Exception:
    _dg = None
try:
    from . import adaptive as _ad
except Exception:
    _ad = None

STATE_FILE = "state.json"


@dataclass
class TaskState:
    """任务断点状态（落盘到 state.json）。"""
    version: int = 1
    done: List[str] = field(default_factory=list)       # 成功的镜头/节点 id
    failed: List[str] = field(default_factory=list)      # 失败的
    pending: List[str] = field(default_factory=list)     # 未做的
    results: Dict[str, Any] = field(default_factory=dict)  # id -> 产物路径/分数
    updated_at: str = ""


def _state_path(workdir: str) -> str:
    return os.path.join(workdir, STATE_FILE)


def load_state(workdir: str) -> TaskState:
    p = _state_path(workdir)
    if not os.path.exists(p):
        return TaskState()
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    st = TaskState()
    st.done = d.get("done", [])
    st.failed = d.get("failed", [])
    st.pending = d.get("pending", [])
    st.results = d.get("results", {})
    st.updated_at = d.get("updated_at", "")
    return st


def save_state(workdir: str, st: TaskState):
    """落盘状态机；保留 record_metrics 写过的 metrics 键（adaptive 反哺依赖）。"""
    st.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    data = st.__dict__.copy()
    sp = _state_path(workdir)
    if os.path.exists(sp):
        try:
            with open(sp, encoding="utf-8") as f:
                ex = json.load(f)
            if "metrics" in ex:
                data["metrics"] = ex["metrics"]
        except Exception:
            pass
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_pipeline(all_tasks: List[str], workdir: str,
                 runner: Callable[[str], Any],
                 resume: bool = True,
                 record: bool = True,
                 tier: str = "T1",
                 node_id: str = "video_shot",
                 model_impl: str = "auto",
                 quant_dtype: str = "unknown",
                 profile: Optional[Dict[str, Any]] = None,
                 scenario: str = "",
                 combo: Optional[Dict[str, str]] = None,
                 node_cfg: Optional[Dict[str, Any]] = None,
                 free_vram_gb: float = 6.0,
                 max_retries: int = 2,
                 mode: str = "beginner") -> Dict[str, Any]:
    """执行任务管线，支持断点重跑。

    all_tasks: 全量任务 id 列表（保持顺序）
    runner(id): 执行单个任务，返回产物/结果；抛异常=失败
    resume: True 则复用 state.json 中已 done 的任务
    返回：本次实际执行的 id、成功数、失败数、跳过数。
    """
    os.makedirs(workdir, exist_ok=True)
    st = load_state(workdir) if resume else TaskState()
    _mode = str(mode or "beginner").lower()
    if _mode not in {"beginner", "pro", "expert"}:
        _mode = "beginner"
    _retries_hint = {"beginner": 1, "pro": 2, "expert": 3}.get(_mode, max_retries)

    if resume:
        st.pending = [t for t in all_tasks if t not in st.done and t not in st.results]
    else:
        st = TaskState(pending=list(all_tasks), done=[], failed=[], results={})

    executed = []
    for tid in all_tasks:
        if tid in st.done:
            continue  # 断点复用
        import time as _t
        _t0 = _t.time()
        _impl = model_impl
        _route = None
        out = None
        _last_err = None
        for _attempt in range(max_retries + 1):
            try:
                # runner 若接受 model_impl 参数则透传当前 impl（OOM/超时换 impl 后生效）
                import inspect
                _sig = inspect.signature(runner)
                if "model_impl" in _sig.parameters:
                    out = runner(tid, model_impl=_impl)
                else:
                    out = runner(tid)
                _last_err = None  # 成功清错误
                break
            except Exception as e:
                _last_err = e
                _err_s = str(e)
                # 三失败类型识别
                _failure = ("quality" if ("quality" in _err_s.lower())
                            else ("oom" if ("OOM" in _err_s.upper() or "MEMORY" in _err_s.upper())
                                  else "timeout"))
                # 失败路由
                if _dg is not None and node_cfg is not None:
                    _route = _dg.route_fallback(node_cfg, free_vram_gb=free_vram_gb,
                                                failure=_failure)
                else:
                    _route = {"level": _attempt, "impl_name": None,
                              "reason": f"{_failure} -> level {_attempt} (无 node_cfg)",
                              "adjust": {}}
                # 记录实机指标（带 scenario + combo，供双维学习）
                if record and _rm is not None:
                    _rm.record_step(
                        workdir, tid, tier=tier, node_id=node_id,
                        model_impl=_impl, quant_dtype=quant_dtype,
                        oom_degraded=(_failure == "oom"),
                        redo_queued=True,
                        shot_elapsed_s=round(_t.time() - _t0, 2),
                        profile=profile, scenario=scenario, combo=combo)
                # 路由决策：OOM/超时换 impl 重试；质量收紧参数（留原 impl）
                if _failure == "quality":
                    # 质量：保留 impl，记下路由决策，最后一次尝试时收紧参数
                    pass
                else:
                    _impl = _route.get("impl_name") or _impl
        # 重试结束：成功 or 耗尽
        _elapsed = round(_t.time() - _t0, 2)
        if out is not None and _last_err is None:
            # 成功：也采实机指标（peak_vram + elapsed + scenario + combo），供双维学习
            if record and _rm is not None:
                _pk = (out.get("peak_vram_gb") if isinstance(out, dict) else None)
                _mk = (out.get("model_impl") if isinstance(out, dict) and out.get("model_impl")
                       else _impl)
                _rm.record_step(
                    workdir, tid, tier=tier, node_id=node_id,
                    model_impl=_mk, quant_dtype=quant_dtype,
                    oom_degraded=bool(out.get("oom_degraded")) if isinstance(out, dict) else False,
                    redo_queued=False,
                    peak_vram_gb=_pk,
                    shot_elapsed_s=(out.get("shot_elapsed_s") if isinstance(out, dict)
                                    and out.get("shot_elapsed_s") is not None else _elapsed),
                    profile=profile, scenario=scenario, combo=combo)
            if isinstance(out, dict) and _route is not None:
                out["_failure_route"] = _route
            st.results[tid] = out
            st.done.append(tid)
            if tid in st.pending:
                st.pending.remove(tid)
            if tid in st.failed:
                st.failed.remove(tid)
        else:
            # 重试耗尽仍失败
            if isinstance(out, dict):
                out["_failure_route"] = _route
                out.setdefault("error", str(_last_err))
            st.results[tid] = out if out is not None else {"error": str(_last_err), "_failure_route": _route}
            st.failed.append(tid)
            if tid in st.pending:
                st.pending.remove(tid)
        executed.append(tid)
        save_state(workdir, st)  # 每步落盘，保证可断点

    # 双维 combo 学习：管线跑完，把本次指标喂给 adaptive，写回 matrix
    _combo_learned = None
    if record and _ad is not None and scenario:
        try:
            _rows = _rm.load_history(workdir)
            _learned = _ad.combo_learn(_rows)
            _combo_learned = _learned
        except Exception:
            _combo_learned = None

    return {
        "executed": executed,
        "success": len([t for t in executed if t in st.done]),
        "failed": len(st.failed),
        "skipped_reused": len(all_tasks) - len(executed),
        "remaining_failed": list(st.failed),
        "mode": _mode,
        "mode_retries_hint": _retries_hint,
    }
