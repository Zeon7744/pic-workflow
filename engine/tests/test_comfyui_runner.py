# -*- coding: utf-8 -*-
"""ComfyUI runner 接 orchestrator 真链路验证（mock 模式 + 自动降级）。

覆盖 8 节点编排实跑循环的 runner 接入：
- detect_comfyui_service 探测 + 不可用降级 mock
- ComfyUIRunner mock 模式：成功 / 12GB 模型 OOM
- 接 orchestrator 真链路：10 镜头实跑 + 指标采集 + 双维学习
- shot_elapsed_s 优先用 runner 返回值（非 wall-clock）
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf import orchestrator as orch
from picwf import comfyui_runner as cr
from picwf import record_metrics as rm


class TestComfyUIRunner:
    """ComfyUI runner 接 orchestrator 真链路。"""

    def test_detect_service_returns_structured(self):
        """detect_comfyui_service 返回结构正确（用必失败端口，环境无关）。"""
        svc = cr.detect_comfyui_service("http://127.0.0.1:59999")
        assert "available" in svc and "url" in svc and "gpu" in svc and "error" in svc
        # 59999 端口无服务，必探测失败
        assert svc["available"] is False, f"无服务应探测失败，实际 {svc}"
        assert svc["error"], "探测失败应有 error 信息"

    def test_mock_mode_success(self):
        """mock 模式：4GB 模型成功，peak_vram=4.0/elapsed=54s。"""
        runner = cr.make_comfyui_runner(mock_fallback=True)
        runner._mock_mode = True
        out = runner.exec("shot_1", model_impl="wan13b_gguf_q4_offload_480")
        assert out["ok"] is True
        assert out["peak_vram_gb"] == 4.0
        assert out["shot_elapsed_s"] == 54.0
        assert out["mock"] is True

    def test_mock_mode_12gb_oom(self):
        """mock 模式：12GB sdxl 模型在 6GB 卡上 OOM。"""
        runner = cr.make_comfyui_runner(mock_fallback=True)
        runner._mock_mode = True
        try:
            runner.exec("shot_1", model_impl="sdxl_anime_lora")
            assert False, "12GB 模型应 OOM"
        except MemoryError as e:
            assert "out of memory" in str(e).lower()
            assert "12GB" in str(e)

    def test_runner_integration_10_shots(self):
        """接 orchestrator 真链路：1060 T1 暗色惊悚 10 镜头实跑。"""
        runner = cr.make_comfyui_runner(mock_fallback=True)
        runner._mock_mode = True
        node_cfg = {"id": "video_shot", "fallback_chain": [
            {"impl": "wan13b_gguf_q4_offload_480"}, {"impl": "cloud_kling"}],
            "current_level": 0}
        workdir = tempfile.mkdtemp(prefix="picwf_comfy_10_")
        res = orch.run_pipeline(
            [f"shot_{i}" for i in range(1, 11)], workdir, runner.exec,
            resume=True, record=True, tier="T1", node_id="video_shot",
            model_impl="wan13b_gguf_q4_offload_480", quant_dtype="q4",
            scenario="dark_thriller",
            combo={"style": "S8", "music": "M5", "voice": "V7", "bgm": "B22"},
            node_cfg=node_cfg, free_vram_gb=6.0, max_retries=2)
        assert res["success"] == 10, f"10 镜头应全成功，实际 success={res['success']}"
        assert res["failed"] == 0
        rows = rm.load_history(workdir)
        assert len(rows) == 10, f"应采 10 条指标，实际 {len(rows)}"
        # shot_elapsed_s 应优先用 runner 返回的 54s（非 wall-clock）
        assert rows[0]["shot_elapsed_s"] == 54.0, \
            f"elapsed 应 54s（runner 返回），实际 {rows[0]['shot_elapsed_s']}"
        # 双维学习
        from picwf import adaptive as ad
        learned = ad.combo_learn(rows)
        assert "dark_thriller::T1" in learned
        assert learned["dark_thriller::T1"]["samples"] == 10
        assert learned["dark_thriller::T1"]["oom_rate"] == 0.0

    def test_runner_backward_compat_default_args(self, monkeypatch):
        """ComfyUIRunner 默认参数（强制 ComfyUI 不可用）自动 mock，环境无关。"""
        monkeypatch.setattr(cr, "detect_comfyui_service",
                           lambda *a, **k: {"available": False, "url": "x",
                                             "gpu": {}, "error": "offline"})
        runner = cr.make_comfyui_runner()
        assert runner.is_mock is True, "ComfyUI 不可用应自动 mock"
        out = runner.exec("shot_x", model_impl="wan13b_gguf_q4_offload_480")
        assert out["ok"] is True

    def test_factory_returns_comfyui_runner(self):
        """make_comfyui_runner 返回 ComfyUIRunner 实例。"""
        runner = cr.make_comfyui_runner(base_url="http://127.0.0.1:8188",
                                        timeout_s=60.0, mock_fallback=True)
        assert isinstance(runner, cr.ComfyUIRunner)
        assert runner.base_url == "http://127.0.0.1:8188"
        assert runner.timeout_s == 60.0
