# -*- coding: utf-8 -*-
"""voice_tts: 声音轨 TTS 统一接入层。

双路线(白皇 2026-10-28 提"做出自己的 TTS"):
1. openai_compat: OpenAI 兼容 /v1/audio/speech(可指豆包/MiniMax/任意 OpenAI 兼容端点)
2. edge: edge-tts 本地兜底(免 key, 网络可用即可), 多语种/多音色

接口:
  synthesize(text, voice, rate, pitch, out_path=None, provider="auto")
    -> {"ok": bool, "provider": str, "out_path": str, "audio_url": str, "error": str}

voice 选择与剧种联动(与 audio_advisor.voice_tracks 对齐):
  - 默认 zh-CN 男/女/童声(edge-tts 音色)
  - provider=openai_compat 时 voice 用目标服务的音色 ID
环境变量:
  TTS_OPENAI_BASE_URL / TTS_OPENAI_API_KEY / TTS_OPENAI_MODEL
  TTS_EDGE 音色覆盖(如 zh-CN-YunxiNeural)
"""
import os
import json
import time
import urllib.request
from typing import Any, Dict, Optional

_OPENAI_BASE = os.environ.get("TTS_OPENAI_BASE_URL", "").rstrip("/")
_OPENAI_KEY = os.environ.get("TTS_OPENAI_API_KEY", "")
_OPENAI_MODEL = os.environ.get("TTS_OPENAI_MODEL", "tts-1")
_EDGE_DEFAULT = os.environ.get("TTS_EDGE", "zh-CN-YunxiNeural")

VOICE_PRESET = {
    "male": "zh-CN-YunxiNeural",
    "female": "zh-CN-XiaoxiaoNeural",
    "child": "zh-CN-XiaoyiNeural",
    "narrator": "zh-CN-YunfengNeural",
    "warm": "zh-CN-XiaoshuangNeural",
    "serious": "zh-CN-YunyangNeural",
    "default": "zh-CN-YunxiNeural",
}


def _resolve_voice(voice: str) -> str:
    return VOICE_PRESET.get((voice or "default"), _EDGE_DEFAULT)


def _provider_available(provider: str) -> bool:
    if provider == "edge":
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False
    if provider == "openai_compat":
        return bool(_OPENAI_KEY)
    return False


def _do_edge(text, voice, rate, pitch, out_path):
    import asyncio
    import edge_tts

    async def _run():
        tts = edge_tts.Communicate(text, _resolve_voice(voice))
        with open(out_path, "wb") as f:
            async for chunk in tts.stream():
                if chunk.get("type") == "audio":
                    f.write(chunk.get("data", b""))
        return out_path

    try:
        asyncio.run(_run())
        return {"ok": True, "provider": "edge", "out_path": out_path,
                "audio_url": out_path, "error": ""}
    except Exception as e:
        # 网络不可达/403 等 -> 优雅降级, 不阻塞出片
        try:
            os.remove(out_path)
        except Exception:
            pass
        return {"ok": False, "provider": "edge", "out_path": out_path,
                "audio_url": "", "error": "edge-tts 网络合成失败: %s" % e}


def _do_openai(text, voice, out_path, response_format="mp3"):
    base = _OPENAI_BASE or "https://api.openai.com/v1"
    body = json.dumps({"model": _OPENAI_MODEL, "input": text,
                       "voice": voice or "alloy", "response_format": response_format}).encode()
    req = urllib.request.Request(f"{base}/audio/speech", data=body,
        headers={"Authorization": f"Bearer {_OPENAI_KEY}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio_bytes = resp.read()
        if not audio_bytes:
            raise RuntimeError("OpenAI TTS 返回空音频")
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return {"ok": True, "provider": "openai_compat", "out_path": out_path,
                "audio_url": out_path, "error": ""}
    except Exception as e:
        return {"ok": False, "provider": "openai_compat", "out_path": out_path,
                "audio_url": "", "error": str(e)}


def synthesize(text, voice="default", rate="+0%", pitch="+0Hz",
               out_path=None, provider="auto", response_format="mp3",
               tmp_dir="tts_out"):
    os.makedirs(tmp_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(tmp_dir, f"tts_{int(time.time()*1000)}.{response_format}")
    if provider == "auto":
        if _provider_available("openai_compat"):
            provider = "openai_compat"
        elif _provider_available("edge"):
            provider = "edge"
        else:
            return {"ok": False, "provider": "none", "out_path": out_path,
                    "audio_url": "", "error": "无可用 TTS 后端(需 TTS_OPENAI_API_KEY 或 pip install edge-tts)"}
    if provider == "openai_compat":
        if not _provider_available("openai_compat"):
            return {"ok": False, "provider": "openai_compat", "out_path": out_path,
                    "audio_url": "", "error": "缺少 TTS_OPENAI_API_KEY / TTS_OPENAI_BASE_URL"}
        return _do_openai(text, voice, out_path, response_format)
    elif provider == "edge":
        if not _provider_available("edge"):
            return {"ok": False, "provider": "edge", "out_path": out_path,
                    "audio_url": "", "error": "edge-tts 未安装:pip install edge-tts"}
        return _do_edge(text, voice, rate, pitch, out_path)
    else:
        return {"ok": False, "provider": provider, "out_path": out_path,
                "audio_url": "", "error": f"未知 provider {provider}"}


def list_voices(provider="edge"):
    if provider == "edge":
        if not _provider_available("edge"):
            return {"ok": False, "voices": [], "error": "edge-tts 未安装"}
        return {"ok": True, "provider": "edge", "voices": list(VOICE_PRESET.values())}
    return {"ok": True, "provider": provider,
            "voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]}


def batch_synthesize(lines, voice="default", tmp_dir="tts_out", provider="auto"):
    results = {}
    for line_id, text in lines.items():
        rp = f"{tmp_dir}/line_{line_id}.mp3"
        results[line_id] = synthesize(text, voice=voice, out_path=rp,
                                      provider=provider, tmp_dir=tmp_dir)
    ok = all(r.get("ok") for r in results.values())
    return {"ok": ok, "results": results}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="声音轨 TTS")
    p.add_argument("text")
    p.add_argument("--voice", default="default")
    p.add_argument("--provider", default="auto", choices=["auto", "edge", "openai_compat"])
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    out = synthesize(args.text, voice=args.voice, provider=args.provider, out_path=args.out)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
