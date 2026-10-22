# -*- coding: utf-8 -*-
"""ComfyUI 实跑 runner：包装 ComfyUI `POST /prompt` API，作为 orchestrator runner。

职责：
- 探测本地 ComfyUI 服务（默认 http://127.0.0.1:8188）
- 把 workflow_gen 生成的节点逐个喂给 ComfyUI
- 采实机指标（peak_vram / elapsed / OOM / redo）回灌 record_metrics
- 支持断点重跑（orchestrator 主链路已实现）

ComfyUI 不可用时降级到 mock_runner（纯 Python 模拟，用于离线验证）。
"""
import json
import os
import time
from typing import Any, Dict, Optional

# ComfyUI 默认端口
COMFYUI_DEFAULT_URL = "http://127.0.0.1:8188"
COMFYUI_HISTORY_LIMIT = 10


def detect_comfyui_service(base_url: str = COMFYUI_DEFAULT_URL) -> Dict[str, Any]:
    """探测本地 ComfyUI 服务是否可用。

    返回 {"available": bool, "url": str, "error": Optional[str]}。
    不抛异常，调用方按需降级到 mock_runner。
    """
    import urllib.request
    url = f"{base_url}/system_stats"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        # 检查 GPU 信息
        gpus = data.get("devices", [])
        gpu_info = gpus[0] if gpus else {}
        return {
            "available": True,
            "url": base_url,
            "gpu": {
                "name": gpu_info.get("name"),
                "vram_total_mb": gpu_info.get("vram_total"),
                "vram_used_mb": gpu_info.get("vram_used"),
            },
            "error": None,
        }
    except Exception as e:
        return {"available": False, "url": base_url, "gpu": {}, "error": str(e)}


class ComfyUIRunner:
    """包装 ComfyUI 实跑，作为 orchestrator 的 runner。

    用法：
        runner = ComfyUIRunner(comfyui_url="http://127.0.0.1:8188")
        res = orchestrator.run_pipeline(
            ["shot_1", "shot_2", ...], workdir,
            runner.exec,  # 注意是 bound method
            ...)

    runner.exec(tid, model_impl="auto") -> dict
        返回 {"ok": bool, "peak_vram_gb": float, "model_impl": str, "error": str}
    """

    def __init__(self,
                 base_url: str = COMFYUI_DEFAULT_URL,
                 timeout_s: float = 120.0,
                 mock_fallback: bool = True):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.mock_fallback = mock_fallback
        self._service = detect_comfyui_service(base_url)
        self._mock_mode = not self._service["available"] and mock_fallback

    @property
    def is_mock(self) -> bool:
        return self._mock_mode

    @property
    def service_available(self) -> bool:
        return self._service["available"]

    def exec(self, tid: str, model_impl: str = "auto") -> Dict[str, Any]:
        """执行单个镜头/节点的 ComfyUI 实跑。

        成功返回 {"ok": True, "peak_vram_gb": float, "model_impl": str}
        失败抛异常（OOMError / TimeoutError / QualityError），orchestrator 捕获后路由。
        """
        if self._mock_mode:
            return self._mock_exec(tid, model_impl)
        return self._comfyui_exec(tid, model_impl)

    def _comfyui_exec(self, tid: str, model_impl: str) -> Dict[str, Any]:
        """真·ComfyUI 实跑：POST /prompt + 轮询 /history。"""
        import urllib.request
        # 构造 ComfyUI prompt（MVP：简化为单节点）
        prompt = {
            "shot_id": tid,
            "model_impl": model_impl,
            "nodes": {
                "1": {"class_type": model_impl, "inputs": {"shot_id": tid}}
            },
            "class_type": "RunPrompt",
        }
        # POST /prompt
        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=json.dumps({"prompt": prompt}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                pr = json.loads(resp.read().decode())
            prompt_id = pr.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 无 prompt_id: {pr}")
        except Exception as e:
            raise RuntimeError(f"ComfyUI POST /prompt 失败: {e}") from e

        # 轮询 /history/{prompt_id}
        deadline = t0 + self.timeout_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"{self.base_url}/history/{prompt_id}",
                        timeout=5) as resp:
                    h = json.loads(resp.read().decode())
                if prompt_id in h:
                    # 完成
                    out = h[prompt_id].get("outputs", {})
                    elapsed = round(time.time() - t0, 2)
                    # 采显存（从 /system_stats）
                    peak_vram = self._sample_vram()
                    return {
                        "ok": True,
                        "model_impl": model_impl,
                        "peak_vram_gb": peak_vram,
                        "shot_elapsed_s": elapsed,
                        "comfyui_prompt_id": prompt_id,
                    }
            except Exception:
                pass
            time.sleep(0.5)
        # 超时
        raise TimeoutError(f"ComfyUI 超时 {self.timeout_s}s prompt_id={prompt_id}")

    def _sample_vram(self) -> float:
        """采样 ComfyUI 当前显存（MB → GB）。"""
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f"{self.base_url}/system_stats", timeout=3) as resp:
                data = json.loads(resp.read().decode())
            gpus = data.get("devices", [])
            if gpus:
                return round(gpus[0].get("vram_used", 0) / 1024 / 1024, 2)
        except Exception:
            pass
        return 0.0

    def _mock_exec(self, tid: str, model_impl: str) -> Dict[str, Any]:
        """mock 模式：纯 Python 模拟 ComfyUI 行为（用于离线验证）。

        - 默认成功，peak_vram=4.0（1060 T1 实机基线）
        - 若 model_impl 是 heavy（12GB sdxl）则模拟 OOM
        """
        import random
        time.sleep(0.05)  # 模拟耗时
        if model_impl in ("sdxl_anime_lora", "sdxl_gguf_q4_offload_768"):
            # 12GB 模型在 6GB 卡上 OOM
            raise MemoryError(
                f"CUDA out of memory: {model_impl} 需 12GB > 6GB free")
        return {
            "ok": True,
            "model_impl": model_impl,
            "peak_vram_gb": 4.0,
            "shot_elapsed_s": 54.0,  # 1060 T1 实测基线
            "mock": True,
        }


def make_comfyui_runner(base_url: str = COMFYUI_DEFAULT_URL,
                        timeout_s: float = 120.0,
                        mock_fallback: bool = True) -> ComfyUIRunner:
    """工厂：创建 ComfyUIRunner。ComfyUI 不可用时自动 mock 降级。"""
    return ComfyUIRunner(base_url=base_url, timeout_s=timeout_s,
                        mock_fallback=mock_fallback)


def main(argv=None):
    """CLI 入口：探测 ComfyUI 服务 + 跑 1 镜头 mock 验证。"""
    import argparse
    p = argparse.ArgumentParser(description="ComfyUI 实跑 runner")
    p.add_argument("--url", default=COMFYUI_DEFAULT_URL,
                   help=f"ComfyUI 服务地址（默认 {COMFYUI_DEFAULT_URL}）")
    p.add_argument("--mock", action="store_true",
                   help="强制 mock 模式（不连 ComfyUI）")
    p.add_argument("--shot", default="shot_test_1", help="测试镜头 id")
    args = p.parse_args(argv)

    # 探测
    svc = detect_comfyui_service(args.url)
    print(f"ComfyUI 服务: {svc['url']}")
    print(f"  available: {svc['available']}")
    print(f"  gpu: {svc['gpu']}")
    print(f"  error: {svc['error']}")

    # 跑 1 镜头：--mock 强制 mock；不传则自动探测（不可用降级 mock）
    if args.mock:
        runner = ComfyUIRunner(base_url=args.url, mock_fallback=False)
        runner._mock_mode = True  # 强制 mock
        print("\n模式: mock（强制）")
    else:
        runner = ComfyUIRunner(base_url=args.url, mock_fallback=True)
        print(f"\n模式: {'mock（自动降级）' if runner.is_mock else 'comfyui 实跑'}")
    out = runner.exec(args.shot, model_impl="wan13b_gguf_q4_offload_480")
    print(f"  结果: {json.dumps(out, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    main()
