# -*- coding: utf-8 -*-
"""Agnes Image 2.5 Flash 图片生成 API 接入。
https://wiki.agnes-ai.cn/llms.txt
"""
from typing import Any, Dict
from .config import get_key, has_key


def run_image(
    prompt: str,
    size: str = "1K",
    ratio: str = "1:1",
    image: list = None,
    return_base64: bool = False,
) -> Dict[str, Any]:
    """调用 Agnes Image 2.5 Flash API。

    Args:
        prompt: 图像生成/编辑指令
        size: 输出尺寸档位（1K/2K/3K/4K），默认 1K
        ratio: 宽高比（1:1/16:9/9:16 等），默认 1:1
        image: 图生图或多图合成参考图像 URL/Base64 列表（可选）
        return_base64: 是否返回 Base64（默认 URL）

    Returns:
        {"ok": True, "image_url": "...", "backend": "agnes_image"} 或
        {"ok": False, "error": "...", "backend": "agnes_image"}
    """
    api_key = get_key("agnes_image")
    if not api_key:
        return {
            "ok": False,
            "error": "AGNES_IMAGE_API_KEY 未配置",
            "backend": "agnes_image",
        }

    import json
    import urllib.request
    import urllib.error

    url = "https://api.agnes-ai.cn/v1/images/generations"
    body = {
        "model": "agnes-image-2.5-flash",
        "prompt": prompt,
        "size": size,
        "ratio": ratio,
    }

    extra = {}
    if image:
        extra["image"] = image
    if return_base64:
        extra["response_format"] = "b64_json"
    else:
        extra["response_format"] = "url"
    body["extra_body"] = extra

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("data", [])
        if not items:
            return {
                "ok": False,
                "error": "API 未返回图像数据",
                "backend": "agnes_image",
            }
        item = items[0]
        return {
            "ok": True,
            "image_url": item.get("url"),
            "b64_json": item.get("b64_json"),
            "revised_prompt": item.get("revised_prompt"),
            "backend": "agnes_image",
            "model": "agnes-image-2.5-flash",
        }
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"HTTP {e.code}: {err_body}", "backend": "agnes_image"}
    except Exception as e:
        return {"ok": False, "error": str(e), "backend": "agnes_image"}
