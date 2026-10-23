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
                 mock_fallback: bool = True,
                 workdir: Optional[str] = None,
                 max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.mock_fallback = mock_fallback
        self.workdir = workdir
        self.max_retries = max_retries
        self._completed: Dict[str, Dict[str, Any]] = {}  # 断点：tid -> 结果
        self._service = detect_comfyui_service(base_url)
        self._mock_mode = not self._service["available"] and mock_fallback
        # 断点恢复：从 workdir/comfyui_results.jsonl 读已完成 tid
        if self.workdir:
            self._restore_checkpoint()

    def _restore_checkpoint(self):
        """从 workdir 读已完成的 tid，断点重跑复用结果。"""
        import os
        if not self.workdir:
            return
        p = os.path.join(self.workdir, "comfyui_results.jsonl")
        if not os.path.exists(p):
            return
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    self._completed[r["tid"]] = r
                except Exception:
                    pass

    def _save_checkpoint(self, tid: str, result: Dict[str, Any]):
        """落盘单 tid 结果（供断点重跑）。"""
        import os
        if not self.workdir:
            return
        os.makedirs(self.workdir, exist_ok=True)
        with open(os.path.join(self.workdir, "comfyui_results.jsonl"),
                  "a", encoding="utf-8") as f:
            f.write(json.dumps({"tid": tid, **result}, ensure_ascii=False) + "\n")

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
        断点：workdir 已提供且 tid 已完成时直接复用结果，不重复提交 ComfyUI。
        """
        # 断点复用
        if tid in self._completed:
            # 返回与正常路径一致的字段（去掉落盘记录的 tid 键）
            rec = dict(self._completed[tid])
            rec.pop("tid", None)
            return rec
        if self._mock_mode:
            out = self._mock_exec(tid, model_impl)
        else:
            out = self._comfyui_exec(tid, model_impl)
        # 成功后落断点
        if out.get("ok"):
            self._save_checkpoint(tid, out)
            self._completed[tid] = out
        return out

    def _comfyui_exec(self, tid: str, model_impl: str) -> Dict[str, Any]:
        """真·ComfyUI 实跑：POST /prompt + 轮询 /history。

        错误分类（供 orchestrator 三失败路由）：
        - OOM   : 显存爆 → MemoryError("CUDA out of memory")
        - 超时  : 轮询超 deadline → TimeoutError
        - 质量  : 输出质量不过 → ValueError("quality: ...")
        重试：网络抖动自动重试 max_retries 次（不消耗 orchestrator 的失败路由配额）。
        """
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
        t0 = time.time()
        last_err = None
        for _attempt in range(self.max_retries + 1):
            # POST /prompt（网络抖动重试）
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/prompt",
                    data=json.dumps({"prompt": prompt}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    pr = json.loads(resp.read().decode())
                prompt_id = pr.get("prompt_id")
                if not prompt_id:
                    raise RuntimeError(f"ComfyUI 无 prompt_id: {pr}")
                break
            except Exception as e:
                last_err = e
                if _attempt >= self.max_retries:
                    # 分类：显存相关 → OOM，其他 → 网络
                    _msg = str(e).lower()
                    if "memory" in _msg or "vram" in _msg or "cuda" in _msg:
                        raise MemoryError(f"CUDA out of memory ({model_impl}): {e}") from e
                    raise RuntimeError(f"ComfyUI POST /prompt 失败(重试{self.max_retries}次): {e}") from e
            last_err = None

        # 轮询 /history/{prompt_id}（deadline 内）
        deadline = t0 + self.timeout_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"{self.base_url}/history/{prompt_id}",
                        timeout=5) as resp:
                    h = json.loads(resp.read().decode())
                if prompt_id in h:
                    out = h[prompt_id].get("outputs", {})
                    elapsed = round(time.time() - t0, 2)
                    peak_vram = self._sample_vram()
                    # 质量检测（MVP：简化为检查输出非空）
                    if not out:
                        raise ValueError(f"quality: 空输出 {model_impl} {tid}")
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
        raise TimeoutError(f"ComfyUI 超时 {self.timeout_s}s prompt_id={prompt_id} ({model_impl})")

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
                        mock_fallback: bool = True,
                        workdir: Optional[str] = None,
                        max_retries: int = 2) -> ComfyUIRunner:
    """工厂：创建 ComfyUIRunner。ComfyUI 不可用时自动 mock 降级。

    workdir 提供后启用断点重跑（已完成 tid 复用结果，不重复提交 ComfyUI）。
    """
    return ComfyUIRunner(base_url=base_url, timeout_s=timeout_s,
                        mock_fallback=mock_fallback,
                        workdir=workdir, max_retries=max_retries)


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
