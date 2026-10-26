# -*- coding: utf-8 -*-
"""Agnes Video 2.5 Flash API 接入。
OpenAI Videos 兼容接口，支持文生视频/首尾帧/图片参考三种模式。

文档: https://wiki.agnes-ai.cn/zh-Hans/docs/agnes-video-25-flash.md
"""
import json
import time
from typing import Any, Dict, List, Optional
from .config import get_key, has_key


API_BASE = "https://api.agnes-ai.cn/v1"
QUERY_BASE = "https://api.agnes-ai.cn/agnesapi"
MODEL = "agnes-video-2.5-flash"
SIZE = "720P"          # Flash 唯一支持的尺寸
DEFAULT_RATIO = "16:9"
RATIOS = ("21:9","16:9","4:3","1:1","3:4","9:16")


def _req(method: str, path: str, body: Optional[Dict] = None,
         timeout: int = 120) -> Dict[str, Any]:
    """通用 HTTP 请求，含 4xx/5xx 错误体解析。"""
    import urllib.request
    import urllib.error
    url = f"{API_BASE}{path}" if not path.startswith("http") else path
    headers = {"Authorization": f"Bearer {get_key('agnes_video')}",
               "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {err_body}")


def _post(path: str, body: Dict) -> Dict:
    return _req("POST", path, body, timeout=30)


def _get(path: str) -> Dict:
    return _req("GET", path, timeout=30)


def run_shot(
    prompt: str,
    mode: str = "text",
    first_frame: Optional[str] = None,
    last_frame: Optional[str] = None,
    images: Optional[List[str]] = None,
    audios: Optional[List[str]] = None,
    ratio: str = DEFAULT_RATIO,
    seconds: int = 5,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """单镜头视频生成：创建任务 + 轮询，同步返回。

    Args:
        prompt: 视频描述提示词
        mode: "text"（文生视频）/ "keyframe"（首尾帧控制）/ "reference"（图片/音频参考）
        first_frame: 首帧图片 URL（keyframe 模式至少提供其一）
        last_frame: 尾帧图片 URL
        images: 参考图片 URL 列表，Flash 最多 5 张
        audios: 参考音频 URL 列表，Flash 最多 3 段
        ratio: 宽高比，默认 16:9（实际 1280×704），也支持 9:16/21:9 等
        seconds: 视频时长字符串 "4"–"12"，默认 "5"
        seed: 随机种子（可选）

    Returns:
        {"ok": True, "video_url": "...", "video_id": "...", "backend": "agnes_video"} 或
        {"ok": False, "error": "...", "backend": "agnes_video"}
    """
    if not has_key("agnes_video"):
        return {"ok": False, "error": "AGNES_VIDEO_API_KEY 未配置",
                "backend": "agnes_video"}

    if ratio not in RATIOS:
        ratio = DEFAULT_RATIO

    body: Dict[str, Any] = {
        "model": MODEL,
        "prompt": prompt,
        "mode": mode,
        "size": SIZE,
        "aspect_ratio": ratio,
        "seconds": str(seconds),
    }

    # 按模式补充媒体字段
    if mode == "keyframe":
        if first_frame:
            body["first_frame"] = first_frame
        if last_frame:
            body["last_frame"] = last_frame
    elif mode == "reference":
        if images:
            body["images"] = images[:5]       # Flash 限制最多 5 张
        if audios:
            body["audios"] = audios[:3]       # Flash 限制最多 3 段
    # text 模式不传媒体字段

    if seed is not None:
        body["seed"] = seed

    try:
        resp = _post("/videos", body)
    except Exception as e:
        return {"ok": False, "error": f"创建任务失败: {e}", "backend": "agnes_video"}

    video_id = resp.get("video_id") or resp.get("id")
    if not video_id:
        return {"ok": False, "error": f"未获取到 video_id: {resp}",
                "backend": "agnes_video"}

    return poll(video_id, timeout=300)


def poll(video_id: str, timeout: int = 300) -> Dict[str, Any]:
    """轮询视频任务结果。

    使用 video_id + model_name 方式查询（支持所有模式）。
    """
    import urllib.request
    url = f"{QUERY_BASE}?video_id={video_id}&model_name={MODEL}"
    headers = {"Authorization": f"Bearer {get_key('agnes_video')}"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        status = data.get("status", "UNKNOWN")
        if status == "completed":
            return {"ok": True, "video_url": data.get("url"),
                    "video_id": video_id, "backend": "agnes_video"}
        if status == "failed":
            return {"ok": False, "error": data.get("error", "任务失败"),
                    "video_id": video_id, "backend": "agnes_video"}
        time.sleep(2)
    return {"ok": False, "error": f"轮询超时（{timeout}s）",
            "video_id": video_id, "backend": "agnes_video"}
