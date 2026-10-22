# -*- coding: utf-8 -*-
"""orchestrator 主链路接入三失败路由 + 双维 combo 学习 验证。"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf import orchestrator as orch
from picwf import record_metrics as rm


class OOMError(Exception):
    pass


_NODE = {
    "id": "video_shot", "name": "④ 视频镜头",
    "fallback_chain": [
        {"impl": "wan13b_gguf_q4_offload_480", "estimated_vram_need_gb": 5},
        {"impl": "cloud_kling", "estimated_vram_need_gb": 0},
        {"impl": "wan13b_fa_480", "estimated_vram_need_gb": 5},
    ],
    "current_level": 0,
}


def _runner_oom_retry(tid, model_impl="auto"):
    """shot_2/shot_3 OOM 后换 cloud_kling 成功。"""
    if tid in ("shot_2", "shot_3") and model_impl == "wan13b_gguf_q4_offload_480":
        raise OOMError("CUDA out of memory")
    return {"ok": True, "peak_vram_gb": 2.0, "model_impl": model_impl}


def _runner_always_fail(tid, model_impl="auto"):
    """重试耗尽仍失败。"""
    raise OOMError("OOM no matter what")


def _runner_ok(tid, model_impl="auto"):
    """全成功。"""
    return {"ok": True, "peak_vram_gb": 4.0, "model_impl": model_impl}


class TestOrchestratorLoop:
    """orchestrator 主链路接入三失败路由 + 双维学习。"""

    def test_oom_auto_route_retry_success(self):
        """OOM 自动路由跳级换 cloud_kling 重试成功。"""
        workdir = tempfile.mkdtemp(prefix="picwf_orch_oom_")
        res = orch.run_pipeline(
            ["shot_1", "shot_2", "shot_3"], workdir, _runner_oom_retry,
            resume=True, record=True, tier="T1", node_id="video_shot",
            model_impl="wan13b_gguf_q4_offload_480", quant_dtype="q4",
            scenario="dark_thriller",
            combo={"style": "S8", "music": "M5", "voice": "V7", "bgm": "B22"},
            node_cfg=_NODE, free_vram_gb=6.0, max_retries=2)
        assert res["success"] == 3, f"OOM 换 impl 后 3 镜头应全成功，实际 success={res['success']}"
        assert res["failed"] == 0
        st = orch.load_state(workdir)
        assert st.results["shot_2"]["model_impl"] == "cloud_kling"
        assert st.results["shot_3"]["model_impl"] == "cloud_kling"
        assert st.results["shot_2"]["_failure_route"]["impl_name"] == "cloud_kling"

    def test_retry_exhausted_goes_failed(self):
        """重试耗尽仍失败 → 进 failed + 路由决策记录。"""
        workdir = tempfile.mkdtemp(prefix="picwf_orch_fail_")
        res = orch.run_pipeline(
            ["shot_x"], workdir, _runner_always_fail,
            resume=True, record=True, tier="T1", node_id="video_shot",
            model_impl="wan13b_gguf_q4_offload_480", quant_dtype="q4",
            scenario="dark_thriller",
            combo={"style": "S8", "music": "M5", "voice": "V7", "bgm": "B22"},
            node_cfg=_NODE, free_vram_gb=6.0, max_retries=2)
        assert res["failed"] == 1, "重试耗尽应进 failed"
        st = orch.load_state(workdir)
        assert "shot_x" in st.failed
        assert st.results["shot_x"].get("error")
        assert st.results["shot_x"]["_failure_route"]["impl_name"]

    def test_metrics_collected_with_scenario_combo(self):
        """实机指标带 scenario + combo 字段采集，供双维学习。"""
        workdir = tempfile.mkdtemp(prefix="picwf_orch_metrics_")
        orch.run_pipeline(
            ["shot_1"], workdir, _runner_ok,
            resume=True, record=True, tier="T1", node_id="video_shot",
            model_impl="wan13b_gguf_q4_offload_480", quant_dtype="q4",
            scenario="dark_thriller",
            combo={"style": "S8", "music": "M5", "voice": "V7", "bgm": "B22"},
            node_cfg=_NODE, free_vram_gb=6.0, max_retries=2)
        rows = rm.load_history(workdir)
        assert len(rows) >= 1
        assert rows[0]["scenario"] == "dark_thriller", "scenario 应采集"
        assert rows[0]["combo"].get("style") == "S8", "combo 应采集"

    def test_backward_compat_no_node_cfg(self):
        """不传 node_cfg 时向后兼容（无路由也正常跑）。"""
        workdir = tempfile.mkdtemp(prefix="picwf_orch_compat_")
        res = orch.run_pipeline(
            ["shot_1"], workdir, _runner_ok,
            resume=True, record=False, tier="T1", node_id="video_shot")
        assert res["success"] == 1, "无 node_cfg 向后兼容应正常跑"

    def test_quality_failure_keep_impl(self):
        """质量失败保留 impl（不跳级），路由决策 keep_impl=True。"""
        def _runner_quality(tid, model_impl="auto"):
            if tid == "shot_q" and model_impl == "wan13b_gguf_q4_offload_480":
                raise Exception("quality: blurry")
            return {"ok": True, "peak_vram_gb": 4.0, "model_impl": model_impl}
        workdir = tempfile.mkdtemp(prefix="picwf_orch_quality_")
        res = orch.run_pipeline(
            ["shot_q"], workdir, _runner_quality,
            resume=True, record=True, tier="T1", node_id="video_shot",
            model_impl="wan13b_gguf_q4_offload_480", quant_dtype="q4",
            scenario="dark_thriller", node_cfg=_NODE,
            free_vram_gb=6.0, max_retries=2)
        st = orch.load_state(workdir)
        r = st.results["shot_q"]
        # 质量失败 keep_impl，路由到 wan13b（level 0 留档）
        assert r["_failure_route"]["impl_name"] == "wan13b_gguf_q4_offload_480"
        assert r["_failure_route"]["adjust"].get("keep_impl") is True
