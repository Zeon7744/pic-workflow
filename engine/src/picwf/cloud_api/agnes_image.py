# -*- coding: utf-8 -*-
"""Agnes 图像生成接入。

用途：
- 分镜关键帧（storyboard）真实出图
- 视频配额受限时，用「真实分镜图 + 缓慢推拉」做动态分镜（animatic），
  成本 0 且远好于占位测试图案

实测 2026-10-28：agnes-image-2.5-flash / 2.1-flash 免费档可用，
返回 data[0].url（COS 链接），需下载成本地文件。
"""
import json
import os
import time
from typing import Any, Dict, Optional

from .config import get_key, has_key
from .agnes_video import download, _post

# 出图接口耗时波动大（i2i 更慢），给足超时并允许重试
_TIMEOUT_S = 150

IMAGE_FLASH = "agnes-image-2.5-flash"
IMAGE_FLASH_OLD = "agnes-image-2.1-flash"
RATIOS = ("1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9")
_QUEUE_HINTS = ("queue_full", "queue full", "队列已满", "繁忙", "rate limit",
                 "timed out", "timeout", "connection reset", "temporarily")


def _is_busy(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in _QUEUE_HINTS)


def run_image(prompt: str, out_path: str = "", ratio: str = "9:16",
              model: Optional[str] = None, retry: int = 4,
              ref_image=None) -> Dict[str, Any]:
    """出图并下载到本地。返回 {ok, path, image_url, model, error}。

    ref_image: 参考图公网 URL（str）或 URL 列表。传了就走路图生图（/images/i2i/），
    用于锁定角色长相——纯文字描述没法保证跨镜头一致。
    """
    if not has_key("agnes_video"):
        return {"ok": False, "path": "", "error": "agnes 密钥未配置",
                "backend": "agnes_image"}
    if not prompt or not prompt.strip():
        return {"ok": False, "path": "", "error": "prompt 为空",
                "backend": "agnes_image"}
    if ratio not in RATIOS:
        ratio = "9:16"
    _model = model or IMAGE_FLASH
    body = {"model": _model, "prompt": prompt, "n": 1,
            "aspect_ratio": ratio, "size": "1K"}
    if ref_image:
        body["image"] = ref_image

    last = ""
    for attempt in range(retry + 1):
        try:
            resp = _post("/images/generations", body, timeout=_TIMEOUT_S)
        except Exception as e:
            last = str(e)
            if not _is_busy(last) or attempt >= retry:
                return {"ok": False, "path": "", "error": f"出图失败: {last}",
                        "backend": "agnes_image", "model": _model}
            time.sleep(min(45, 6 * (attempt + 1)))
            continue
        items = resp.get("data") or []
        url = (items[0] or {}).get("url") if items else ""
        if not url:
            return {"ok": False, "path": "", "error": f"未返回图片: {str(resp)[:200]}",
                    "backend": "agnes_image", "model": _model}
        if not out_path:
            return {"ok": True, "path": "", "image_url": url,
                    "backend": "agnes_image", "model": _model}
        dl = download(url, out_path)
        if dl.get("ok"):
            return {"ok": True, "path": out_path, "image_url": url,
                    "backend": "agnes_image", "model": _model, "error": ""}
        return {"ok": False, "path": "", "image_url": url,
                "error": f"图片下载失败: {dl.get('error')}",
                "backend": "agnes_image", "model": _model}
    return {"ok": False, "path": "", "error": f"重试耗尽: {last}",
            "backend": "agnes_image", "model": _model}
