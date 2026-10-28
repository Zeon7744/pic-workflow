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
# 白皇 22:05 边界：引擎侧默认 flash（限时免费）；pro 只有显式点名才用，
# 禁止在引擎里把 pro 写成默认，否则成本不可控。
MODEL = "agnes-video-2.5-flash"
MODEL_FLASH = "agnes-video-2.5-flash"
MODEL_PRO = "agnes-video-2.5"
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
    model: Optional[str] = None,
    out_path: Optional[str] = None,
    queue_retry: int = 8,
    timeout: int = 900,
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
        model: 模型名，默认 agnes-video-2.5-flash；传 MODEL_PRO 才走付费档
        out_path: 给了就把视频下载到该本地路径（下游剪辑必须拿到本地文件）
        queue_retry: 队列满（video_queue_full）时的退避重试次数

    Returns:
        {"ok": True, "video_url": "...", "video_id": "...", "backend": "agnes_video"} 或
        {"ok": False, "error": "...", "backend": "agnes_video"}
    """
    if not has_key("agnes_video"):
        return {"ok": False, "error": "AGNES_VIDEO_API_KEY 未配置",
                "backend": "agnes_video"}

    if ratio not in RATIOS:
        ratio = DEFAULT_RATIO

    _model = model or MODEL
    body: Dict[str, Any] = {
        "model": _model,
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

    # 队列满（video_queue_full）是常态，退避重试，不要当失败直接放弃镜头
    resp: Dict[str, Any] = {}
    last = ""
    for attempt in range(queue_retry + 1):
        try:
            resp = _post("/videos", body)
        except Exception as e:
            last = str(e)
            if not _is_queue_full(last) or attempt >= queue_retry:
                return {"ok": False, "error": f"创建任务失败: {last}",
                        "backend": "agnes_video"}
            time.sleep(min(120, 12 * (attempt + 1)))
            continue
        msg = json.dumps(resp, ensure_ascii=False)
        if _is_queue_full(msg) and attempt < queue_retry:
            last = msg
            time.sleep(min(120, 12 * (attempt + 1)))
            continue
        break

    video_id = resp.get("video_id") or resp.get("id")
    if not video_id:
        return {"ok": False, "error": f"未获取到 video_id: {resp}",
                "backend": "agnes_video"}

    result = poll(video_id, timeout=timeout, model=_model)
    result["model"] = _model
    if result.get("ok") and out_path and result.get("video_url"):
        dl = download(result["video_url"], out_path)
        result["path"] = dl.get("path", "")
        if not dl.get("ok"):
            # 下载失败必须显式标注：URL 会过期，没有本地文件下游就用不了
            result["ok"] = False
            result["error"] = f"视频已生成但下载失败: {dl.get('error')}"
    return result


_QUEUE_HINTS = ("video_queue_full", "queue full", "队列已满", "queue_full")


def _is_queue_full(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in _QUEUE_HINTS)


def download(url: str, out_path: str) -> Dict[str, Any]:
    """把生成结果下载成本地文件。

    没有这一步，下游剪辑只能拿到一个会过期的 URL，等于没产出。
    """
    import os
    import urllib.request
    try:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with urllib.request.urlopen(url, timeout=180) as r:
            data = r.read()
        if not data:
            return {"ok": False, "path": "", "error": "下载内容为空"}
        with open(out_path, "wb") as f:
            f.write(data)
        return {"ok": True, "path": out_path, "bytes": len(data)}
    except Exception as e:
        return {"ok": False, "path": "", "error": str(e)}


def poll(video_id: str, timeout: int = 900,
         model: Optional[str] = None) -> Dict[str, Any]:
    """轮询视频任务结果。

    使用 video_id + model_name 方式查询（支持所有模式）。
    """
    import urllib.request
    url = f"{QUERY_BASE}?video_id={video_id}&model_name={model or MODEL}"
    headers = {"Authorization": f"Bearer {get_key('agnes_video')}"}
    deadline = time.time() + timeout
    errs = 0
    while time.time() < deadline:
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            errs = 0
        except Exception as e:
            # 轮询接口偶发抖动不该直接判失败，连续 5 次才放弃
            errs += 1
            if errs >= 5:
                return {"ok": False, "error": f"轮询连续失败: {e}",
                        "video_id": video_id, "backend": "agnes_video"}
            time.sleep(3)
            continue
        status = data.get("status", "UNKNOWN")
        if status == "completed":
            return {"ok": True, "video_url": data.get("url"),
                    "video_id": video_id, "backend": "agnes_video"}
        if status == "failed":
            return {"ok": False, "error": data.get("error", "任务失败"),
                    "video_id": video_id, "backend": "agnes_video"}
        time.sleep(5)
    return {"ok": False, "error": f"轮询超时（{timeout}s），任务可能仍在生成",
            "video_id": video_id, "model": model or MODEL,
            "backend": "agnes_video"}
