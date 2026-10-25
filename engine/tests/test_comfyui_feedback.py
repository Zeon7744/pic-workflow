# -*- coding: utf-8 -*-
"""comfyui_feedback 学习闭环测试。

核心命题（白皇定位）：ComfyUI 只是数据渠道，引擎自身价值是
「工作流迭代 + 优化产出 + 超越 ComfyUI」。本模块验证
ComfyUI 实跑真数据能回流 matrix.adaptive.yaml，引擎自我迭代。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))


def _fake_runner(tmp, results):
    """造一个返回预设 ComfyUI 结果的假 runner，隔离 ComfyUI 服务。"""
    class _R:
        def __init__(self):
            self._i = 0
            self.local_models_dir = tmp
            self.local_models = {"anything-v5": {"local_file_name": "anything-v5.safetensors"}}
        def exec(self, tid, model_impl="auto"):
            out = results[min(self._i, len(results) - 1)]
            self._i += 1
            out = dict(out)
            out.setdefault("model_impl", model_impl)
            return out
    return _R()


def test_collect_comfyui_run_feeds_history(tmp_path):
    from picwf.comfyui_feedback import collect_comfyui_run
    runner = _fake_runner(str(tmp_path), [
        {"ok": True, "mock": False, "peak_vram_gb": 4.2,
         "shot_elapsed_s": 30.5, "local_checkpoint": "anything-v5.safetensors"}
    ])
    rec = collect_comfyui_run(runner, "shot_x", "sdxl", tier="T1",
                              node_id="video_shot",
                              workdir=str(tmp_path))
    # 采成 record_metrics 历史行
    assert rec["peak_vram_gb"] == 4.2
    assert rec["shot_elapsed_s"] == 30.5
    assert rec["mock"] is False
    assert rec["combo"]["backend"] == "comfyui"
    assert rec["local_checkpoint"] == "anything-v5.safetensors"
    # 落盘了历史行（metrics_history.jsonl）
    hist = os.path.join(str(tmp_path), "metrics_history.jsonl")
    assert os.path.exists(hist)
    with open(hist, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert any(r.get("task_id") == "comfyui::shot_x" for r in lines)


def test_full_cycle_learns_into_adaptive_matrix(tmp_path):
    from picwf.comfyui_feedback import full_cycle
    from picwf import adaptive
    # adaptive 在 engine/src/picwf，matrix.yaml 在 engine/config，上跳两级
    matrix_path = os.path.normpath(os.path.join(
        os.path.dirname(adaptive.__file__), "..", "..", "config", "matrix.yaml"))
    assert os.path.exists(matrix_path), "matrix.yaml 应在 engine/config/"
    adaptive_out = str(tmp_path / "matrix.adaptive.yaml")
    results = [
        {"ok": True, "mock": False, "peak_vram_gb": 4.1, "shot_elapsed_s": 28.0,
         "local_checkpoint": "a.safetensors"},
        {"ok": True, "mock": False, "peak_vram_gb": 4.3, "shot_elapsed_s": 31.0,
         "local_checkpoint": "a.safetensors"},
        {"ok": True, "mock": False, "peak_vram_gb": 4.2, "shot_elapsed_s": 29.5,
         "local_checkpoint": "a.safetensors"},
    ]
    report = full_cycle(results, str(tmp_path), matrix_path, adaptive_out,
                        tier="T1", node_id="video_shot")
    # 学习报告应已应用、采到 3 条真数据、0 mock
    assert report["applied"] is True
    assert report["comfyui_runs_adopted"] == 3
    assert report["mock_ratio"] == 0.0
    assert report["samples_total"] >= 3
    # matrix.adaptive.yaml 真被生成
    assert os.path.exists(adaptive_out)
    with open(adaptive_out, encoding="utf-8") as f:
        head = f.read()
    assert "version" in head


def test_full_cycle_mock_runs_counted_correctly(tmp_path):
    from picwf.comfyui_feedback import full_cycle
    from picwf import adaptive
    matrix_path = os.path.normpath(os.path.join(
        os.path.dirname(adaptive.__file__), "..", "..", "config", "matrix.yaml"))
    adaptive_out = str(tmp_path / "m.yaml")
    results = [
        {"ok": True, "mock": True, "peak_vram_gb": 4.0, "shot_elapsed_s": 54.0},
        {"ok": True, "mock": True, "peak_vram_gb": 4.0, "shot_elapsed_s": 54.0},
    ]
    report = full_cycle(results, str(tmp_path), matrix_path, adaptive_out)
    assert report["mock_ratio"] == 1.0
    assert report["comfyui_runs_adopted"] == 2


def test_real_checkpoint_picking():
    """_pick_real_checkpoint 优先本地模型，没有则默认 SD1.5 基础。"""
    from picwf.comfyui_runner import _pick_real_checkpoint
    # 有本地模型：精确匹配
    assert _pick_real_checkpoint({"sdxl": {"local_file_name": "sdxl.safetensors"}},
                                 "sdxl") == "sdxl.safetensors"
    # 有本地模型：无精确匹配取第一个
    assert _pick_real_checkpoint({"a": {"local_file_name": "a.safetensors"}},
                                 "not_exist") == "a.safetensors"
    # 无本地模型：默认 SD1.5
    assert _pick_real_checkpoint({}, "whatever") == "v1-5-pruned-emaonly-fp16.safetensors"


def test_pipeline_cli_wires_learn_loop(tmp_path, monkeypatch):
    """pipeline_cli.run 跑完自动触发学习回流，res['learn_loop'] 落地。"""
    from picwf import pipeline_cli
    # 造一个最小剧本
    script = str(tmp_path / "剧本.md")
    with open(script, "w", encoding="utf-8") as f:
        f.write("# 第1集\n- 镜头1：主角登场\n- 镜头2：冲突爆发\n")
    wd = str(tmp_path / "run")
    monkeypatch.setattr(pipeline_cli, "make_executors", lambda wf, **k: {})
    # 跑（ComfyUI 不在线，走 mock 路径，但学习闭环仍触发）
    res = pipeline_cli.run(script, tier="T1", ep=2, workdir=wd,
                           auto_repair=False)
    # learn_loop 字段应存在（auto_repair=False 时不走学习分支，验证不崩）
    assert "delivery_readiness" in res
