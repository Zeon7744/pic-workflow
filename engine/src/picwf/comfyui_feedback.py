# -*- coding: utf-8 -*-
"""comfyui_feedback：把 ComfyUI 实跑真数据回流到引擎学习闭环。

定位（白皇 2026-10-25 强调）：ComfyUI 只是「出品/测试数据渠道」，
引擎自身价值是「工作流迭代 + 优化产出 + 超越 ComfyUI 的独立功能」。

本模块做的是引擎的独立价值核心：
  ComfyUI 实跑结果 → record_metrics 历史行 → adaptive.run_feedback
  → matrix.adaptive.yaml（档位×节点矩阵被实机数据持续校准）
  → 下一轮工作流生成拿到「更准」的 fallback_chain 优先级 + 显存预估

ComfyUI 跑完一次，引擎就比上一次更聪明。ComfyUI 是数据源，不是目的地。
"""
from typing import Any, Dict, List, Optional


def collect_comfyui_run(runner: Any,
                        tid: str,
                        model_impl: str,
                        tier: str = "T1",
                        node_id: str = "video_shot",
                        scenario: str = "dark_thriller",
                        quant_dtype: str = "bf16",
                        profile: Optional[Dict[str, Any]] = None,
                        workdir: str = "./_pipe_cli") -> Dict[str, Any]:
    """对单个 ComfyUI 实跑结果，采真数据 → record_metrics 历史行。"""
    from .record_metrics import record_step
    out = runner.exec(tid, model_impl=model_impl)
    rec = record_step(
        workdir,
        task_id="comfyui::" + tid,
        tier=tier,
        node_id=node_id,
        model_impl=model_impl,
        quant_dtype=quant_dtype,
        oom_degraded=bool(out.get("oom_degraded", False)),
        redo_queued=bool(out.get("redo_queued", False)),
        peak_vram_gb=float(out.get("peak_vram_gb", 0.0) or 0.0),
        shot_elapsed_s=float(out.get("shot_elapsed_s", 0.0) or 0.0),
        profile=profile,
        scenario=scenario,
        combo={"backend": "comfyui" if not out.get("mock") else "comfyui_mock",
               "local_checkpoint": out.get("local_checkpoint", ""),
               "local_models_dir": out.get("local_models_dir", "")},
    )
    rec["mock"] = bool(out.get("mock", False))
    rec["local_checkpoint"] = out.get("local_checkpoint", "")
    return rec


def learn_from_comfyui_runs(workdir: str,
                            matrix_path: str,
                            adaptive_out_path: str) -> Dict[str, Any]:
    """把 workdir 里已采的 ComfyUI 实跑历史，回流到 matrix.adaptive.yaml。

    调 adaptive.run_feedback，返回 {samples_total, cells, before_after, applied}。
    下一轮 generate_workflow 若指向 adaptive_out_path，即拿到被实跑校准过的矩阵。
    """
    from .adaptive import run_feedback
    return run_feedback(workdir, matrix_path, adaptive_out_path)


def full_cycle(comfyui_results: List[Dict[str, Any]],
               workdir: str,
               matrix_path: str,
               adaptive_out_path: str,
               tier: str = "T1",
               node_id: str = "video_shot",
               scenario: str = "dark_thriller") -> Dict[str, Any]:
    """完整闭环：ComfyUI 实跑结果 → 采历史 → 回流 matrix → 返回学习报告。

    comfyui_results: runner.exec 的多次结果（含 mock/真跑混合）。
    返回学习报告，engine 的下一轮工作流生成可据此迭代。
    """
    from .record_metrics import record_step
    from .adaptive import run_feedback

    adopted = []
    for i, out in enumerate(comfyui_results):
        rec = record_step(
            workdir,
            task_id="comfyui_batch::" + str(i),
            tier=tier,
            node_id=node_id,
            model_impl=out.get("model_impl", "auto"),
            quant_dtype="bf16",
            oom_degraded=bool(out.get("oom_degraded", False)),
            redo_queued=bool(out.get("redo_queued", False)),
            peak_vram_gb=float(out.get("peak_vram_gb", 0.0) or 0.0),
            shot_elapsed_s=float(out.get("shot_elapsed_s", 0.0) or 0.0),
            scenario=scenario,
            combo={"backend": "comfyui" if not out.get("mock") else "comfyui_mock",
                   "local_checkpoint": out.get("local_checkpoint", ""),
                   "local_models_dir": out.get("local_models_dir", "")},
        )
        adopted.append(rec)

    report = run_feedback(workdir, matrix_path, adaptive_out_path)
    report["comfyui_runs_adopted"] = len(adopted)
    # mock_ratio：comfyui_mock 后端占比（ComfyUI 离线降级为纯模拟的）
    _mock_cnt = sum(1 for a in adopted
                     if a.get("combo", {}).get("backend") == "comfyui_mock")
    report["mock_ratio"] = round(_mock_cnt / max(1, len(adopted)), 2)
    report["real_ratio"] = round(1 - _mock_cnt / max(1, len(adopted)), 2)
    report["note"] = ("ComfyUI 实跑数据已回流 matrix.adaptive.yaml，"
                      "引擎下一轮生成工作流会拿到被实机校准的档位矩阵")
    return report
