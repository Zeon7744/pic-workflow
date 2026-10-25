import io
# -*- coding: utf-8 -*-
"""workflow_explorer 主动探索 + 工作流产出单测。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def _sample_matrix():
    return {
        "version": "test",
        "tiers": ["T0", "T1", "T2"],
        "nodes": [
            {"id": "video_shot", "fallback_chain": {
                "T1": [
                    {"impl": "wan13b_gguf_q4_offload_480",
                     "estimated_vram_need_gb": 5},
                    {"impl": "cloud_kling", "estimated_vram_need_gb": 0},
                    {"impl": "wan13b_fa_480", "estimated_vram_need_gb": 5},
                ],
                "T2": [
                    {"impl": "wan13b_fa_480", "estimated_vram_need_gb": 9},
                    {"impl": "cloud_kling", "estimated_vram_need_gb": 0},
                ],
            }},
        ],
    }


def _history_one_run():
    """video_shot/T1/wan13b_gguf_q4_offload_480 已被跑过且 OOM 低（视为已验证）。"""
    return [
        {"tier": "T1", "node_id": "video_shot",
         "model_impl": "wan13b_gguf_q4_offload_480",
         "peak_vram_gb": 4.2, "shot_elapsed_s": 18.0, "oom_degraded": False},
        {"tier": "T1", "node_id": "video_shot",
         "model_impl": "wan13b_gguf_q4_offload_480",
         "peak_vram_gb": 4.5, "shot_elapsed_s": 19.0, "oom_degraded": False},
    ]


def test_next_plan_prioritizes_untested_local():
    from picwf import workflow_explorer as we
    plan = we.next_exploration_plan(_sample_matrix(), _history_one_run(), top_k=5)
    # 至少返回候选
    assert isinstance(plan, list) and len(plan) > 0
    # 未验证 + 本地 gguf 安全 的组合应排前
    top = plan[0]
    assert top["model_impl"] in ("wan13b_gguf_q4_offload_480", "wan13b_fa_480")
    # 每个项有打分字段
    for it in plan:
        assert "score" in it and "risk" in it and "untested" in it


def test_verified_cell_not_marked_untested():
    from picwf import workflow_explorer as we
    plan = we.next_exploration_plan(_sample_matrix(), _history_one_run(), top_k=10)
    # wan13b_gguf_q4_offload_480 在 T1 已被充分验证（OOM 低），应 untested=False
    matched = [it for it in plan
               if it["model_impl"] == "wan13b_gguf_q4_offload_480" and it["tier"] == "T1"]
    assert matched, "T1 gguf 组合应在候选里"
    assert matched[0]["untested"] is False


def test_emit_workflow_is_real_comfyui_graph():
    from picwf import workflow_explorer as we
    plan = we.next_exploration_plan(_sample_matrix(), [], top_k=3)
    assert plan
    out = we.emit_comfyui_workflow(plan[0],
                                   checkpoint="anything-v5-PrtRE.safetensors",
                                   prompt="a hero in dark alley",
                                   seed=42)
    wf = out["workflow"]
    # 真实 7 节点图
    assert wf["1"]["class_type"] == "CheckpointLoaderSimple"
    assert wf["5"]["class_type"] == "KSampler"
    assert wf["6"]["class_type"] == "VAEDecode"
    assert wf["7"]["class_type"] == "SaveImage"
    # checkpoint 注入
    assert wf["1"]["inputs"]["ckpt_name"] == "anything-v5-PrtRE.safetensors"
    # payload 带探索信息
    assert out["payload_for_prompt_endpoint"]["model_impl"] == plan[0]["model_impl"]


def test_emit_batch_one_workflow_per_plan_item():
    from picwf import workflow_explorer as we
    plan = we.next_exploration_plan(_sample_matrix(), [], top_k=4)
    batch = we.emit_exploration_batch(plan, checkpoint="any.safetensors")
    assert len(batch) == len(plan)
    for b in batch:
        assert "workflow" in b and "payload_for_prompt_endpoint" in b


def test_high_vram_cell_penalized_in_plan():
    from picwf import workflow_explorer as we
    # T1 档位上限 6GB，T2 的 wan13b_fa_480 est_vram=9>6 应被扣分
    m = _sample_matrix()
    # 只取 T1 + 一个超高显存 impl 放 T1 chain
    m["nodes"][0]["fallback_chain"]["T1"].insert(0,
        {"impl": "huge_local_1080", "estimated_vram_need_gb": 20})
    plan = we.next_exploration_plan(m, [], top_k=20)
    by_impl = {it["model_impl"]: it for it in plan if it["tier"] == "T1"}
    if "huge_local_1080" in by_impl and "wan13b_gguf_q4_offload_480" in by_impl:
        # 超高显存组合分数应低于本地 gguf 安全组合
        assert (by_impl["huge_local_1080"]["score"]
                < by_impl["wan13b_gguf_q4_offload_480"]["score"])


def test_explore_full_cycle_produces_runnable_batch(tmp_path, monkeypatch):
    from picwf import workflow_explorer as we
    # 写一份最小 matrix + history
    import json
    matrix_path = tmp_path / "matrix.yaml"
    matrix_path.write_text(
        "version: test\ntiers: [T1]\nnodes:\n"
        "  - id: video_shot\n    fallback_chain:\n"
        "      T1:\n"
        "        - impl: wan13b_gguf_q4_offload_480\n"
        "          estimated_vram_need_gb: 5\n"
        "        - impl: cloud_kling\n"
        "          estimated_vram_need_gb: 0\n",
        encoding="utf-8")
    workdir = tmp_path / "wd"
    workdir.mkdir()
    # 造 history（record_metrics 用 jsonl）
    hist_file = workdir / "metrics_history.jsonl"
    hist_file.write_text(json.dumps({
        "tier": "T1", "node_id": "video_shot",
        "model_impl": "wan13b_gguf_q4_offload_480",
        "peak_vram_gb": 4.3, "shot_elapsed_s": 18.5, "oom_degraded": False,
    }) + "\n" + json.dumps({
        "tier": "T1", "node_id": "video_shot",
        "model_impl": "wan13b_gguf_q4_offload_480",
        "peak_vram_gb": 4.4, "shot_elapsed_s": 19.0, "oom_degraded": False,
    }) + "\n", encoding="utf-8")

    adaptive_out = tmp_path / "matrix.adaptive.yaml"
    rep = we.explore_full_cycle(str(workdir), str(matrix_path),
                                str(adaptive_out), top_k=3)
    assert rep["ready_for_run"] is True
    assert rep["workflows"] == len(rep["exploration"])
    assert rep["learn"]["applied"] is True
    # 工作流 payload 可执行（含 prompt 端点要的 7 节点）
    for w in rep["workflows_payload"]:
        assert w["workflow"]["5"]["class_type"] == "KSampler"


def test_apply_exploration_results_adopts_and_applies(tmp_path):
    """explore→回灌结果采 metrics→run_feedback 回流，applied=True"""
    from picwf import workflow_explorer as we
    import yaml, os, json

    mx = os.path.join(str(tmp_path), "matrix.yaml")
    ad = os.path.join(str(tmp_path), "matrix.adaptive.yaml")
    base = tmp_path / "runs"
    base.mkdir()

    with io.open(r"C:\Users\Administrator\pic-push\engine\config\matrix.yaml", "r", encoding="utf-8") as f:
        m = yaml.safe_load(f)
    with io.open(mx, "w", encoding="utf-8") as f:
        yaml.safe_dump(m, f, allow_unicode=True)

    from picwf.record_metrics import load_history

    # 探索回灌结果（2个成功，1个失败）
    batch_results = [
        {"ok": True, "status": "completed", "plan_item": {"tier": "T2", "node": "video_shot", "model_impl": "ltx095_fp16_720", "impl": "ltx095_fp16_720", "expected_vram": 11.0}},
        {"ok": True, "status": "completed", "plan_item": {"tier": "T1", "node": "video_shot", "model_impl": "wan13b_fa_fp16_480", "impl": "wan13b_fa_fp16_480", "expected_vram": 13.0}},
        {"ok": False, "status": "failed", "plan_item": {"tier": "T0", "node": "storyboard_prompt", "model_impl": "hf_zero", "impl": "hf_zero", "expected_vram": 1.0}},
    ]

    out = we.apply_exploration_results(batch_results, str(tmp_path), mx, ad, scenario="dark_thriller")
    assert out["adopted"] == 3
    assert out["applied"] is True, f"learn applied should be True, got {out['learn']}"
    assert os.path.exists(ad)
    # 回流后历史里应有 3 条探索记录
    h2 = load_history(str(tmp_path))
    exp = [x for x in h2 if str(x.get("task_id", "")).startswith("exploration::")]
    assert len(exp) == 3
    print("    P0 apply_exploration_results adopted + applied OK")


def test_explore_and_learn_returns_full_loop(tmp_path):
    """explore_and_learn 完整闭环：探索→回灌→学习，返回 applied 状态"""
    from picwf import workflow_explorer as we
    import yaml, os

    mx = os.path.join(str(tmp_path), "matrix.yaml")
    ad = os.path.join(str(tmp_path), "matrix.adaptive.yaml")
    with io.open(r"C:\Users\Administrator\pic-push\engine\config\matrix.yaml", "r", encoding="utf-8") as f:
        m = yaml.safe_load(f)
    with io.open(mx, "w", encoding="utf-8") as f:
        yaml.safe_dump(m, f, allow_unicode=True)

    # 无 ComfyUI 在线时，batch_results 全部 offline，但流程应完整返回
    out = we.explore_and_learn(
        str(tmp_path), mx, ad,
        base_url="http://127.0.0.1:1",  # 不存在的服务 → offline
        top_k=2,
    )
    assert "exploration" in out
    assert "batch_results" in out
    assert "applied" in out
    assert "explore_learned" in out
    # offline 时 0 成功
    oks = [r for r in out["batch_results"] if r.get("ok")]
    assert len(oks) == 0
    assert out["note"]  # 有说明
    print("    explore_and_learn full loop OK, note:", out["note"])
