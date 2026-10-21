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
    st.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(_state_path(workdir), "w", encoding="utf-8") as f:
        json.dump(st.__dict__, f, ensure_ascii=False, indent=2)


def run_pipeline(all_tasks: List[str], workdir: str,
                 runner: Callable[[str], Any],
                 resume: bool = True) -> Dict[str, Any]:
    """执行任务管线，支持断点重跑。

    all_tasks: 全量任务 id 列表（保持顺序）
    runner(id): 执行单个任务，返回产物/结果；抛异常=失败
    resume: True 则复用 state.json 中已 done 的任务
    返回：本次实际执行的 id、成功数、失败数、跳过数。
    """
    os.makedirs(workdir, exist_ok=True)
    st = load_state(workdir) if resume else TaskState()

    if resume:
        st.pending = [t for t in all_tasks if t not in st.done and t not in st.results]
    else:
        st = TaskState(pending=list(all_tasks), done=[], failed=[], results={})

    executed = []
    for tid in all_tasks:
        if tid in st.done:
            continue  # 断点复用
        try:
            out = runner(tid)
            st.results[tid] = out
            st.done.append(tid)
            if tid in st.pending:
                st.pending.remove(tid)
            if tid in st.failed:
                st.failed.remove(tid)
            executed.append(tid)
            save_state(workdir, st)  # 每步落盘，保证可断点
        except Exception as e:
            st.failed.append(tid)
            if tid in st.pending:
                st.pending.remove(tid)
            st.results[tid] = {"error": str(e)}
            executed.append(tid)
            save_state(workdir, st)

    return {
        "executed": executed,
        "success": len([t for t in executed if t in st.done]),
        "failed": len(st.failed),
        "skipped_reused": len(all_tasks) - len(executed),
        "remaining_failed": list(st.failed),
    }
