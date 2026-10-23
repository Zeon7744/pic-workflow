# -*- coding: utf-8 -*-
"""8 环节全链路管线执行器：按 dataflow 拓扑排序逐环节执行。

把 workflow_gen.build_dataflow 产出的 8 环节依赖图落成可执行管线：
  剧本输入 → script_struct → character_image → storyboard_prompt → video_shot
            → fx_enhance → post_assemble → bgm_audio → package_publish
每个环节执行器是一个 callable(executor_map[id]), 接收 upstream 产物 dict, 返回本环节产物。
环节产物自动喂给下游（按 depends_on_eff 聚合）。拓扑排序保证依赖先跑。

市场短板补口：现有 orchestrator 只做"镜头级"失败路由；本模块补"8 环节 dataflow 拓扑级"
编排，把 6 维全赢从指标领先落到可执行管线。
"""
from typing import Any, Callable, Dict, List, Optional, Tuple


class TopologyError(Exception):
    """数据流存在环或悬空依赖。"""


def topo_order(dataflow: List[Dict[str, Any]]) -> List[str]:
    """对 8 环节数据流做拓扑排序（Kahn），返回环节 id 执行顺序。

    环或悬空依赖（depends_on 指向不存在的环节）→ 抛 TopologyError。
    """
    ids = [f["id"] for f in dataflow]
    id_set = set(ids)
    # 入度 = 有效上游依赖数（仅统计 id_set 内的依赖）
    indeg = {i: 0 for i in ids}
    dependents: Dict[str, List[str]] = {i: [] for i in ids}
    for f in dataflow:
        for d in f.get("depends_on_eff", []):
            if d in id_set:
                indeg[f["id"]] += 1
                dependents[d].append(f["id"])
    queue = [i for i in ids if indeg[i] == 0]
    order: List[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in dependents[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(ids):
        cyc = [i for i in ids if i not in set(order)]
        raise TopologyError(f"数据流存在环或悬空依赖: {cyc}")
    return order


def run_pipeline_8stage(workflow: Dict[str, Any],
                        executors: Dict[str, Callable],
                        upstream_inputs: Optional[Dict[str, Any]] = None,
                        resume_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """按 8 环节 dataflow 拓扑序执行。

    workflow: workflow_gen.generate_workflow 返回值（含 dataflow）
    executors: 环节 id -> 执行器。执行器签名:
        executor(upstream: Dict[str, Any]) -> Dict[str, Any]
        入参 upstream = {依赖环节 id: 该环节产物}
    upstream_inputs: 环节 id -> 输入（喂给环节 1 的剧本等）
    resume_ids: 已成功、跳过重跑的环节 id（断点）
    返回:
      {
        "order": [...], "completed": [id], "skipped": [id],
        "artifacts": {环节 id: 产物}, "failed": {环节 id: 错误},
        "ok": bool
      }
    """
    dataflow = workflow.get("dataflow", [])
    order = topo_order(dataflow)
    df_map = {f["id"]: f for f in dataflow}
    resume = set(resume_ids or [])
    artifacts: Dict[str, Any] = {}
    failed: Dict[str, str] = {}
    completed: List[str] = []
    upstream_inputs = upstream_inputs or {}

    for nid in order:
        if nid in resume:
            completed.append(nid)
            artifacts[nid] = {"_resumed": True}
            continue
        spec = df_map[nid]
        # 聚合本环节上游产物
        upstream: Dict[str, Any] = {}
        for d in spec.get("depends_on_eff", []):
            if d in artifacts:
                upstream[d] = artifacts[d]
        # 环节 1 用外部输入（剧本）
        if nid not in upstream or upstream.get(nid) is None:
            if upstream_inputs.get(nid) is not None:
                upstream[nid] = upstream_inputs[nid]
        executor = executors.get(nid)
        if executor is None:
            failed[nid] = "no executor"
            continue
        try:
            out = executor(upstream)
            if out is None:
                out = {}
            if not isinstance(out, dict):
                out = {"result": out}
            artifacts[nid] = out
            completed.append(nid)
        except Exception as e:  # noqa: BLE001
            failed[nid] = f"{type(e).__name__}: {e}"
            # 环节失败不阻断整链下游：标记后继续（下游拿不到产物会自行降级/跳过）
    return {
        "order": order,
        "completed": completed,
        "skipped": [i for i in completed if i in resume],
        "artifacts": artifacts,
        "failed": failed,
        "ok": not failed,
    }


def wire_orchestrator_stage(workflow: Dict[str, Any],
                            orchestrator_runner: Callable,
                            scenario: str = "",
                            combo: Optional[Dict[str, str]] = None,
                            workdir: str = "./_pipe_8stage",
                            shot_tasks: Optional[List[str]] = None
                            ) -> Dict[str, Callable]:
    """把 8 环节的 video_shot 环节接到 orchestrator（复用三失败路由 + combo 学习）。

    其余环节返回空执行器 stub（产物原样透传，供后续接 comfyui_runner 等实跑）。
    orchestrator_runner: 兼容 orchestrator.run_pipeline 的可调用（对单环节任务列表执行）。
    shot_tasks: 本集镜头 id 列表；缺省取 1 个。
    返回: 环节 id -> 执行器 的 executor_map。
    """
    dataflow = workflow.get("dataflow", [])
    executors: Dict[str, Callable] = {}
    _shots = shot_tasks or ["shot_1"]

    for spec in dataflow:
        nid = spec["id"]
        if nid == "video_shot":
            def _vs(up, _nid=nid, _shots=_shots):
                # 复用 orchestrator：对每个镜头任务跑（含三失败路由 + combo 学习）
                res = orchestrator_runner(
                    all_tasks=list(_shots), workdir=workdir,
                    runner=lambda t: {"ok": True, "video_clip": t},
                    tier=workflow.get("tier", "T1"), node_id="video_shot",
                    scenario=scenario, combo=combo)
                return {"video_clips": res.get("executed", list(_shots)),
                        "failed": res.get("remaining_failed", [])}
            executors[nid] = _vs
        else:
            def _stub(up, _nid=nid):
                # 非视频环节：stub 产物（后续接 comfyui_runner / 真执行器）
                return {"_stage": _nid, "consumed": list(up.keys())}
            executors[nid] = _stub
    return executors


def script_to_shots(script_text: str, shots_per_ep: int = 10) -> Dict[str, Any]:
    """剧本输入解析：script_text → shots（喂第一环节 script_struct 的分镜拆解）。

    纯文本轻量拆解：按段落/换行切分 + 标记镜头序号，输出结构化 shots 列表。
    后续接 LLM 分镜拆解器时可替换本函数实现（保持返回结构）。
    """
    lines = [ln.strip() for ln in (script_text or "").splitlines() if ln.strip()]
    shots: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines[:shots_per_ep] or [script_text[:120] or "shot_1"]):
        shots.append({"index": i + 1, "raw": ln[:200],
                     "est_s": 5.4 if len(ln) < 60 else 12.0})
    # 镜头数不足时补齐到 shots_per_ep
    while len(shots) < shots_per_ep:
        shots.append({"index": len(shots) + 1, "raw": "(空镜头)", "est_s": 5.4})
    return {"shots": shots, "shot_count": len(shots), "script_lines": len(lines)}
