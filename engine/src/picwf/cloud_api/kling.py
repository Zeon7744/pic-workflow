# -*- coding: utf-8 -*-
"""快手可灵（Kling）视频生成 API 接入。"""
import json
import time
from typing import Any, Dict, Optional
from .config import get_key, has_key

API_BASE = "https://api.klingai.com"


def _call_kling(endpoint: str, body: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    api_key = get_key("kling")
    if not api_key:
        raise RuntimeError("KLING_API_KEY 未配置")
    import urllib.request
    url = f"{API_BASE}/{endpoint}"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(url, data=payload,
        headers={"Authorization": f"KlingAI {api_key}", "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def generate_video(
    prompt: str,
    model: str = "kling-v2-6",
    ratio: str = "16:9",
    duration: int = 5,
) -> Dict[str, Any]:
    body = {
        "model": model,
        "prompt": prompt,
        "ratio": ratio,
        "duration": duration,
    }
    resp = _call_kling("v1/videos/text2video", body, timeout=30)
    task_id = resp.get("data", {}).get("task_id") or resp.get("task_id")
    return {"task_id": task_id, "status": resp.get("code", "PENDING"), "raw": resp}


def poll_task(task_id: str, timeout: int = 300, interval: int = 10) -> Dict[str, Any]:
    api_key = get_key("kling")
    url = f"{API_BASE}/v1/videos/tasks/{task_id}"
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(url,
            headers={"Authorization": f"KlingAI {api_key}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        status = data.get("data", {}).get("task_status", "UNKNOWN")
        if status == "success":
            videos = data.get("data", {}).get("task_result", {}).get("videos", [])
            video_url = videos[0].get("url") if videos else None
            return {"task_id": task_id, "status": "SUCCEEDED", "video_url": video_url}
        if status in ("fail",):
            return {"task_id": task_id, "status": "FAILED", "raw": data}
        time.sleep(interval)
    return {"task_id": task_id, "status": "TIMEOUT"}


def run_shot(prompt: str, ratio: str = "16:9", duration: int = 5) -> Dict[str, Any]:
    if not has_key("kling"):
        return {"ok": False, "error": "KLING_API_KEY 未配置", "backend": "kling_cloud"}
    result = generate_video(prompt, ratio=ratio, duration=duration)
    task_id = result.get("task_id")
    if not task_id:
        return {"ok": False, "error": "无法获取 task_id", "backend": "kling_cloud", "raw": result}
    return poll_task(task_id)
