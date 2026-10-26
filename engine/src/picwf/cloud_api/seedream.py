# -*- coding: utf-8 -*-
"""腾讯 Seedream 图片生成 API 接入。"""
import json
from typing import Any, Dict
from .config import get_key, has_key

def run_image(prompt: str, ratio: str = "16:9") -> Dict[str, Any]:
    if not has_key("seedream"):
        return {"ok": False, "error": "SEEDREAM_API_KEY 未配置", "backend": "seedream_cloud"}
    # Seedream REST 调用简化实现（生产环境需完整 TC3 签名）
    api_key = get_key("seedream")
    body = {"Model": "seedream-4.0", "Prompts": [prompt], "Ratio": ratio}
    import urllib.request
    url = "https://api.tencentcloudapi.com/?Action=ImageGeneration"
    payload = json.dumps(body).encode()
    req = urllib.request.Request(url, data=payload,
        headers={"Authorization": f"TC3-HMAC-SHA256 Credential={api_key}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        response = data.get("Response", {})
        task_id = response.get("TaskId")
        images = response.get("ImageResults", [])
        url = images[0].get("Url") if images else None
        return {"ok": True, "task_id": task_id, "image_url": url, "backend": "seedream_cloud"}
    except Exception as e:
        return {"ok": False, "error": str(e), "backend": "seedream_cloud"}
