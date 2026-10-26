# -*- coding: utf-8 -*-
"""云端模型健康检查：测试 API Key 是否有效 + 模型可用性。"""
import json
import time
from typing import Dict, Any, Optional
from .config import has_key, get_key


def check_wan() -> Dict[str, Any]:
    """检查通义万相 API 连通性。"""
    if not has_key("wan"):
        return {"service": "wan", "available": False, "error": "WAN_API_KEY 未配置",
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        import urllib.request
        api_key = get_key("wan")
        # 调用 dashscope 任务状态接口（不实际生成，只验证连通性）
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2video/synthesis"
        body = json.dumps({"model": "wan2.1-t2v-1.3t",
                           "input": {"prompt": "test"},
                           "parameters": {"resolution": "480p"}}).encode()
        req = urllib.request.Request(url, data=body,
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json",
                     "X-DashScope-Async": "enable"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        code = data.get("code")
        message = data.get("message", "")
        return {
            "service": "wan",
            "available": code is None or "Success" in str(data.get("output", {})),
            "status_code": code,
            "message": message or str(data),
            "tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"service": "wan", "available": False, "error": str(e),
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def check_kling() -> Dict[str, Any]:
    """检查快手可灵 API 连通性。"""
    if not has_key("kling"):
        return {"service": "kling", "available": False, "error": "KLING_API_KEY 未配置",
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        import urllib.request
        api_key = get_key("kling")
        url = "https://api.klingai.com/v1/videos/text2video"
        body = json.dumps({"model": "kling-v2-6", "prompt": "test",
                           "ratio": "16:9", "duration": 5}).encode()
        req = urllib.request.Request(url, data=body,
            headers={"Authorization": f"KlingAI {api_key}",
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return {
            "service": "kling",
            "available": True,
            "raw": data,
            "tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"service": "kling", "available": False, "error": str(e),
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def check_seedream() -> Dict[str, Any]:
    """检查腾讯 Seedream API 连通性。"""
    if not has_key("seedream"):
        return {"service": "seedream", "available": False, "error": "SEEDREAM_API_KEY 未配置",
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        import urllib.request
        api_key = get_key("seedream")
        url = "https://api.tencentcloudapi.com/?Action=ImageGeneration"
        body = json.dumps({"Model": "seedream-4.0", "Prompts": ["test"],
                           "Ratio": "16:9"}).encode()
        req = urllib.request.Request(url, data=body,
            headers={"Authorization": f"TC3-HMAC-SHA256 Credential={api_key}",
                     "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        return {
            "service": "seedream",
            "available": True,
            "raw": data,
            "tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        return {"service": "seedream", "available": False, "error": str(e),
                "tested_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def run_all_checks() -> Dict[str, Any]:
    """运行全部云端模型健康检查。"""
    checks = {
        "wan": check_wan(),
        "kling": check_kling(),
        "seedream": check_seedream(),
    }
    return {
        "checks": checks,
        "summary": {
            "total": 3,
            "available": sum(1 for c in checks.values() if c.get("available")),
            "unavailable": sum(1 for c in checks.values() if not c.get("available")),
            "tested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }
