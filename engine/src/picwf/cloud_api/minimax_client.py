#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
minimax_client.py —— MiniMax 客户端（白皇边界：只做声音，不做视频）

【业务边界 2026-10-28】MiniMax 只做声音（TTS），视频统一走 agnes seedance2.0_pro。
H3 视频相关函数保留作存档，不进任何生产选路。

声音能力：tts() 文本转语音 / list_voices() 音色查询 / VOICE_PRESETS 常用音色

按注册表 v1.1 minimax_h3 / minimax_image 规格实现：
  * 视频：POST https://api.minimax.cn/v2/video_generation  → task_id → GET /v2/video_generation/{task_id}
  * 图像：POST https://api.minimax.cn/v1/image_generation → data.image_urls 或 image_base64

约束：
  * key 存 .minimax_key（不进共享/不进记忆）
  * 参考图/视频/音频必须公网 URL（http/https）
  * 首帧/尾帧和多模态参考互斥
  * 768P 输入按 768P 出，2K 输入降到 768P 是官方行为（不额外处理）
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

BASE_URL = "https://api.minimax.cn"
SUBMIT_VIDEO = f"{BASE_URL}/v2/video_generation"
STATUS_VIDEO = f"{BASE_URL}/v2/query/video_generation"  # GET /v2/query/video_generation/{task_id}
IMAGE = f"{BASE_URL}/v1/image_generation"
TTS = f"{BASE_URL}/v1/t2a_v2"          # 文本转语音（白皇边界：MiniMax 唯一用途）
VOICE_LIST = f"{BASE_URL}/v1/get_voice"  # 音色查询


def _load_key() -> tuple[str, str]:
    """读 MiniMax 密钥。优先级：环境变量 > api_keys.env > .minimax_key 文件。

    引擎侧推荐用环境变量 MINIMAX_API_KEY（云部署/CI 友好），
    .minimax_key 仅作本地开发兜底，绝不入库。
    """
    # 1) 环境变量（最高优先级，云部署标准做法）
    env_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if env_key:
        return env_key, os.environ.get("MINIMAX_BASE_URL", "").strip() or BASE_URL

    # 2) engine 的 api_keys.env（与 agnes/wan 等统一入口）
    try:
        from .config import load_api_keys
        keys = load_api_keys()
        k = (keys.get("MINIMAX_API_KEY") or "").strip()
        if k:
            return k, (keys.get("MINIMAX_BASE_URL") or "").strip() or BASE_URL
    except Exception:
        pass

    # 3) .minimax_key 文件（开发兜底）。按优先级逐处查找：
    #    同包目录 -> ~/.minimax_key -> 当前目录 -> 项目共享目录
    _cands = [
        Path(__file__).parent / ".minimax_key",
        Path.home() / ".minimax_key",
        Path(".minimax_key"),
        Path("/Coze/Drive/简化画廊/.minimax_key"),
    ]
    for cand in _cands:
        if cand.exists():
            lines = cand.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            key = lines[0].strip()
            base = lines[1].strip() if len(lines) > 1 and lines[1].startswith("http") else BASE_URL
            return key, base
    raise RuntimeError(
        "未配置 MiniMax 密钥：请设置环境变量 MINIMAX_API_KEY，"
        "或写入 engine/config/api_keys.env，或放 .minimax_key")


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# 限流控制
# MiniMax 有 RPM 上限：一串连续请求会中途开始返回 rate limit exceeded(RPM)。
# 配音是逐句合成，天然会连续打很多条，所以这里做两件事：
#   1) 请求前保证最小间隔，尽量不触发限流
#   2) 真触发了就指数退避重试，不要把「限流」变成「丢台词」
# ---------------------------------------------------------------------------
_MIN_INTERVAL_S = float(os.environ.get("MINIMAX_MIN_INTERVAL_S", "1.5"))
_RETRY_MAX = int(os.environ.get("MINIMAX_RETRY_MAX", "4"))
_RATE_HINTS = ("rate limit", "rpm", "too many", "429", "频繁")
_last_ts = [0.0]


def _throttle() -> None:
    """保证相邻请求间隔不小于 _MIN_INTERVAL_S。"""
    if _MIN_INTERVAL_S <= 0:
        return
    gap = time.time() - _last_ts[0]
    if gap < _MIN_INTERVAL_S:
        time.sleep(_MIN_INTERVAL_S - gap)
    _last_ts[0] = time.time()


def _is_rate_limited(text: str) -> bool:
    low = (text or "").lower()
    return any(h in low for h in _RATE_HINTS)


def _post_retry(url: str, key: str, payload: dict) -> dict:
    """带限流退避的 _post。退避 4/8/16/32s，用尽后抛最后一次错误。"""
    last = ""
    for i in range(_RETRY_MAX + 1):
        _throttle()
        try:
            resp = _post(url, key, payload)
        except RuntimeError as e:
            last = str(e)
            if not _is_rate_limited(last) or i >= _RETRY_MAX:
                raise
            time.sleep(min(32, 4 * (2 ** i)))
            continue
        # 有些限流是 200 + base_resp 里报错
        msg = json.dumps(resp.get("base_resp") or {}, ensure_ascii=False)
        if _is_rate_limited(msg) and i < _RETRY_MAX:
            last = msg
            time.sleep(min(32, 4 * (2 ** i)))
            continue
        return resp
    raise RuntimeError(f"限流重试 {_RETRY_MAX} 次仍失败: {last}")


def _post(url: str, key: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from None


def _get(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers=_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}") from None


def _content_from(
    prompt: str,
    first_frame: str | None = None,
    last_frame: str | None = None,
    ref_images: list[str] | None = None,
    ref_videos: list[str] | None = None,
    ref_audios: list[str] | None = None,
) -> list[dict]:
    """按官方 role 组织 content 数组。首尾帧 与 多模态参考 互斥。"""
    use_ref = bool(ref_images or ref_videos or ref_audios)
    use_kf = bool(first_frame or last_frame)
    if use_ref and use_kf:
        raise ValueError("首尾帧 与 多模态参考 不能同时使用")
    content: list[dict] = [{"type": "text", "text": prompt}]
    if use_kf:
        if first_frame:
            content.append({
                "type": "image_url",
                "image_url": {"url": first_frame},
                "role": "first_frame",
            })
        if last_frame:
            content.append({
                "type": "image_url",
                "image_url": {"url": last_frame},
                "role": "last_frame",
            })
    else:
        for i, u in enumerate(ref_images or [], start=1):
            content.append({
                "type": "image_url",
                "image_url": {"url": u},
                "role": "reference_image",
            })
        for i, u in enumerate(ref_videos or [], start=1):
            content.append({
                "type": "video_url",
                "video_url": {"url": u},
                "role": "reference_video",
            })
        for i, u in enumerate(ref_audios or [], start=1):
            content.append({
                "type": "audio_url",
                "audio_url": {"url": u},
                "role": "reference_audio",
            })
    return content


def submit_video(
    prompt: str,
    resolution: str = "768P",
    duration: int = 6,
    ratio: str = "9:16",
    first_frame: str | None = None,
    last_frame: str | None = None,
    ref_images: list[str] | None = None,
    ref_videos: list[str] | None = None,
    ref_audios: list[str] | None = None,
    seed: int | None = 42,
    aigc_watermark: bool = False,
    model: str = "MiniMax-H3",
) -> str:
    """提交 H3 视频任务，返回 task_id。"""
    if duration < 4 or duration > 15:
        raise ValueError("duration 4-15 整数")
    if resolution not in ("768P", "2K"):
        raise ValueError("resolution 768P/2K")
    payload: dict = {
        "model": model,
        "content": _content_from(
            prompt, first_frame, last_frame, ref_images, ref_videos, ref_audios
        ),
        "resolution": resolution,
        "duration": int(duration),
        "ratio": ratio,
        "aigc_watermark": aigc_watermark,
    }
    if seed is not None:
        payload["seed"] = int(seed)
    key, _ = _load_key()
    resp = _post(SUBMIT_VIDEO, key, payload)
    task_id = resp.get("task_id") or resp.get("id")
    if not task_id:
        raise RuntimeError(f"无 task_id: {json.dumps(resp, ensure_ascii=False)}")
    return str(task_id)


def poll_video(task_id: str, interval: int = 10, timeout: int = 900) -> dict:
    """轮询视频任务，返回 {status, video_url, raw}。"""
    key, _ = _load_key()
    deadline = time.time() + timeout
    url = f"{STATUS_VIDEO}/{task_id}"
    last: dict = {}
    while time.time() < deadline:
        last = _get(url, key)
        # v2 响应格式: {"task": {"status": "succeeded", "content": {"url": "..."}}}
        task_obj = last.get("task") or {}
        state = str(task_obj.get("status") or last.get("status") or last.get("state") or "").lower()
        if state in ("succeeded", "succeed", "success", "completed", "done", "finished"):
            # v2: task.content.url; v1 兼容: video / file / output
            content_obj = task_obj.get("content") or {}
            vurl = content_obj.get("url") if isinstance(content_obj, dict) else None
            if not vurl:
                vurl = (
                    last.get("video") or last.get("file") or last.get("output")
                    or (last.get("data") or {}).get("video")
                )
            if isinstance(vurl, dict):
                vurl = vurl.get("url") or vurl.get("download_url")
            return {"status": "Succeed", "video_url": vurl, "raw": last}
        if state in ("failed", "error", "cancelled", "canceled"):
            task_err = task_obj.get("error") or {}
            return {
                "status": "Failed",
                "video_url": None,
                "reason": task_err or last.get("fail_reason") or last.get("error") or str(last),
                "raw": last,
            }
        time.sleep(interval)
    return {"status": "Timeout", "video_url": None, "reason": "超时", "raw": last}


def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    n: int = 1,
    seed: int | None = 42,
    subject_reference_url: str | None = None,
    width: int | None = None,
    height: int | None = None,
    response_format: str = "url",
    model: str = "image-01",
    aigc_watermark: bool = False,
    prompt_optimizer: bool = False,
) -> dict:
    """image-01 文生图 / 主体参考图生图。"""
    if n < 1 or n > 9:
        raise ValueError("n 1-9")
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": response_format,
        "n": int(n),
        "prompt_optimizer": prompt_optimizer,
        "aigc_watermark": aigc_watermark,
    }
    if seed is not None:
        payload["seed"] = int(seed)
    if subject_reference_url:
        payload["subject_reference"] = [
            {"type": "character", "image_file": subject_reference_url}
        ]
    if width and height:
        payload["width"] = int(width)
        payload["height"] = int(height)
    key, _ = _load_key()
    return _post(IMAGE, key, payload)


# ---------- TTS：对白配音 / 旁白（MiniMax 唯一用途） ----------
# 常用音色预设（短剧对白够用，完整列表用 list_voices() 查）
VOICE_PRESETS = {
    "male_qingse": "male-qn-qingse",        # 男青涩
    "male_jingshen": "male-qn-jingying",    # 男精英
    "male_shaonian": "male-qn-badao",       # 男少年/霸道
    "female_shaonv": "female-shaonv",       # 女少女
    "female_yujie": "female-yujie",         # 女御姐
    "female_tianmei": "female-tianmei",     # 女甜美
}

EMOTIONS = ["happy", "sad", "angry", "fearful", "disgusted", "surprised", "neutral"]


def list_voices(voice_type: str = "all") -> dict:
    """查询可用音色。voice_type: all / system / voice_cloning"""
    key, _ = _load_key()
    return _post(VOICE_LIST, key, {"voice_type": voice_type})


def tts(
    text: str,
    voice_id: str = "male-qn-qingse",
    model: str = "speech-2.5-hd-preview",
    speed: float = 1.0,
    vol: float = 1.0,
    pitch: int = 0,
    emotion: str | None = None,
    fmt: str = "mp3",
    sample_rate: int = 32000,
    bitrate: int = 128000,
    out_path: str | None = None,
) -> dict:
    """文本转语音。返回 {ok, audio_bytes|path, duration_ms, raw_meta}

    MiniMax t2a_v2 返回 data.audio 为 hex 字符串（stream=false 时）。
    """
    if not text or not text.strip():
        raise ValueError("text 不能为空")
    if len(text) > 3000:
        raise ValueError(f"text 超长 {len(text)} > 3000，需分段")
    if emotion and emotion not in EMOTIONS:
        raise ValueError(f"emotion 须为 {EMOTIONS}")

    payload: dict = {
        "model": model,
        "text": text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": float(speed),
            "vol": float(vol),
            "pitch": int(pitch),   # 官方要求 int64（-12~12 半音）
        },
        "audio_setting": {
            "sample_rate": int(sample_rate),
            "bitrate": int(bitrate),
            "format": fmt,
            "channel": 1,
        },
    }
    if emotion:
        payload["voice_setting"]["emotion"] = emotion

    key, _ = _load_key()
    if not key:
        # 本地就拦住：别拿空 key 去撞服务端，省一次往返且错误信息更清楚
        return {"ok": False, "audio_bytes": b"", "path": None, "duration_ms": 0,
                "error": "MiniMax 密钥缺失：请设置 MINIMAX_API_KEY 环境变量，"
                         "或在 ~/.minimax_key 写入密钥"}
    resp = _post_retry(TTS, key, payload)

    base_resp = resp.get("base_resp") or {}
    if base_resp.get("status_code") not in (0, None):
        return {
            "ok": False,
            "error": base_resp.get("status_msg", "unknown"),
            "raw_meta": resp,
        }

    data = resp.get("data") or {}
    hex_audio = data.get("audio")
    if not hex_audio:
        return {"ok": False, "error": "响应无 data.audio", "raw_meta": resp}

    audio_bytes = bytes.fromhex(hex_audio)
    result = {
        "ok": True,
        "size": len(audio_bytes),
        "duration_ms": (resp.get("extra_info") or {}).get("audio_length"),
        "raw_meta": {
            "trace_id": resp.get("trace_id"),
            "extra_info": resp.get("extra_info"),
        },
    }
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(audio_bytes)
        result["path"] = str(out_path)
    else:
        result["audio_bytes"] = audio_bytes
    return result


# ---------- 便捷：本地文件 → 公网 URL 或 base64 data URL ----------
def file_to_data_url(path: Path) -> str:
    raw = Path(path).read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    ext = path.suffix.lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64,{b64}"


# ---------- CLI ----------
def _cli(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    cmd = argv[0]
    if cmd == "check":
        key, base = _load_key()
        print(json.dumps({"key_ok": bool(key), "base": base, "submit_video": SUBMIT_VIDEO, "status": STATUS_VIDEO, "image": IMAGE}, ensure_ascii=False, indent=2))
        return 0

    if cmd == "submit-video":
        rest = argv[1:]
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("prompt")
        p.add_argument("--resolution", default="768P", choices=["768P", "2K"])
        p.add_argument("--duration", type=int, default=6)
        p.add_argument("--ratio", default="9:16")
        p.add_argument("--first-frame")
        p.add_argument("--last-frame")
        p.add_argument("--ref-image", action="append", default=[])
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--watermark", action="store_true")
        a = p.parse_args(rest)
        tid = submit_video(
            a.prompt,
            resolution=a.resolution,
            duration=a.duration,
            ratio=a.ratio,
            first_frame=a.first_frame,
            last_frame=a.last_frame,
            ref_images=a.ref_image or None,
            seed=a.seed,
            aigc_watermark=a.watermark,
        )
        print(json.dumps({"task_id": tid, "status_url": f"{STATUS_VIDEO}/{tid}"}, ensure_ascii=False, indent=2))
        return 0

    if cmd == "poll":
        rest = argv[1:]
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("task_id")
        p.add_argument("--interval", type=int, default=10)
        p.add_argument("--timeout", type=int, default=900)
        a = p.parse_args(rest)
        print(json.dumps(poll_video(a.task_id, a.interval, a.timeout), ensure_ascii=False, indent=2))
        return 0

    if cmd == "image":
        rest = argv[1:]
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("prompt")
        p.add_argument("--aspect", default="1:1")
        p.add_argument("--n", type=int, default=1)
        p.add_argument("--seed", type=int, default=42)
        p.add_argument("--subject-ref")
        p.add_argument("--format", default="url", choices=["url", "base64"])
        p.add_argument("--watermark", action="store_true")
        a = p.parse_args(rest)
        out = generate_image(
            a.prompt,
            aspect_ratio=a.aspect,
            n=a.n,
            seed=a.seed,
            subject_reference_url=a.subject_ref,
            response_format=a.format,
            aigc_watermark=a.watermark,
        )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if cmd == "tts":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("text")
        p.add_argument("--voice", default="male-qn-qingse")
        p.add_argument("--out", required=True)
        p.add_argument("--speed", type=float, default=1.0)
        p.add_argument("--pitch", type=int, default=0)
        p.add_argument("--emotion", default=None)
        p.add_argument("--model", default="speech-2.5-hd-preview")
        a = p.parse_args(argv[1:])
        r = tts(a.text, voice_id=a.voice, model=a.model, speed=a.speed,
                pitch=a.pitch, emotion=a.emotion, out_path=a.out)
        r.pop("audio_bytes", None)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1

    if cmd == "voices":
        print(json.dumps(list_voices(), ensure_ascii=False, indent=2)[:3000])
        return 0

    print(f"未知命令: {cmd}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
