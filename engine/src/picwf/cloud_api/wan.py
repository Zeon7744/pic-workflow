# -*- coding: utf-8 -*-
"""通义万相（Wan）视频生成 API 接入。

文档参考：https://help.aliyun.com/zh/model-studio/developer-reference/wan
"""
import json
import base64
import time
from typing import Any, Dict, List, Optional
from .config import get_key, has_key

API_BASE = "https://dashscope.aliyuncs.com/api/v1"


def _call_dashscope(endpoint: str, body: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    """调用 DashScope 统一 API。"""
    import urllib.request
    api_key = get_key("wan")
    if not api_key:
        raise RuntimeError("WAN_API_KEY 未配置，请在 config/api_keys.env 填写")
    
    url = f"{API_BASE}/{endpoint}"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "DashScope-API-Key": api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def generate_video(
    prompt: str,
    model: str = "wan2.1-t2v-14b",
    resolution: str = "480p",
    duration: int = 5,
    negative_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """发起通义万相视频生成任务（异步）。
    
    返回 task_id，后续需轮询输出。
    """
    body = {
        "model": model,
        "input": {
            "prompt": prompt,
        },
        "parameters": {
            "resolution": resolution,
            "duration": duration,
        }
    }
    if negative_prompt:
        body["input"]["negative_prompt"] = negative_prompt
    
    resp = _call_dashscope("tasks", body, timeout=30)
    task_id = resp.get("output", {}).get("task_id") or resp.get("task_id")
    status = resp.get("output", {}).get("task_status", "PENDING")
    return {"task_id": task_id, "status": status, "response": resp}


def poll_task(task_id: str, timeout: int = 300, interval: int = 10) -> Dict[str, Any]:
    """轮询任务结果。"""
    import urllib.request
    api_key = get_key("wan")
    url = f"{API_BASE}/tasks/{task_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        output = data.get("output", {})
        status = output.get("task_status", "UNKNOWN")
        if status == "SUCCEEDED":
            video_url = (output.get("video_url") 
                        or (output.get("results") or [{}])[0].get("url")
                        or output.get("media", {}).get("video", {}).get("url"))
            return {"task_id": task_id, "status": "SUCCEEDED", "video_url": video_url, "raw": data}
        if status in ("FAILED", "CANCELED"):
            return {"task_id": task_id, "status": status, "raw": data}
        time.sleep(interval)
    return {"task_id": task_id, "status": "TIMEOUT"}


def run_shot(prompt: str, resolution: str = "480p", duration: int = 5) -> Dict[str, Any]:
    """单镜头生成：发起 + 轮询，同步返回。"""
    if not has_key("wan"):
        return {"ok": False, "error": "WAN_API_KEY 未配置", "backend": "wan_cloud"}
    result = generate_video(prompt, resolution=resolution, duration=duration)
    task_id = result.get("task_id")
    if not task_id:
        return {"ok": False, "error": "无法获取 task_id", "backend": "wan_cloud", "raw": result}
    return poll_task(task_id, timeout=300)
