# -*- coding: utf-8 -*-
"""voice_tts: 声音轨 TTS 统一接入层（可插拔多后端）。

三个后端(白皇 2026-10-28 定 MiniMax 只做声音不做视频):
1. minimax: 云端主线。原生 POST /v1/t2a_v2(返回 hex 音频), 无 OpenAI 兼容端点。
   通过 minimax_tts_adapter 转调 minimax_client.tts, 支持情绪(7 种)+角色声线克隆预留。
2. openai_compat: 真 OpenAI 兼容 /v1/audio/speech(豆包/任意兼容厂商)。
   注意: MiniMax 没有此端点, 不要再假定 MiniMax 走这条路。
3. edge: edge-tts 本地兜底(免 key, 本地网络可用), 云端 WSS 被 403 拦截。

统一接口(对齐 model_gateway audio_tts 任务):
  synthesize(text, voice_id="default", emotion="neutral", speed=1.0,
             out_path=None, backend="auto", character=None)
    -> {"ok", "path", "duration_ms", "backend", "voice_id", "emotion", "error"}
  list_voices(backend="auto") -> {"ok", "voices":[...], "backend"}
  batch_synthesize({line_id:text}, voice_id, emotion, backend, out_dir, character)
    -> {"ok", "results", "ok_count", "total_duration_ms"}

向后兼容:
  synthesize 仍接受旧参数名 voice/rate/pitch/provider, 自动映射到新签名。
环境变量:
  MINIMAX_API_KEY / MINIMAX_BASE_URL(或复用 minimax_client 已读到的)
  TTS_OPENAI_BASE_URL / TTS_OPENAI_API_KEY / TTS_OPENAI_MODEL
  TTS_EDGE 音色覆盖
"""
import os
import json
import time
import urllib.request
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# 后端注册
# ---------------------------------------------------------------------------
_BACKENDS = {}
_ADAPTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "..", "..", "minimax_tts_adapter.py")


def _load_minimax_adapter():
    """定位并加载 minimax_tts_adapter(若存在)。返回模块或 None。"""
    if "minimax" in _BACKENDS:
        return _BACKENDS["minimax"]
    import importlib.util
    candidates = [
        _ADAPTER_PATH,
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "minimax_tts_adapter.py"),
        # 项目共享目录兜底(云设备与 Windows 互通)
        os.path.expanduser("~/minimax_tts_adapter.py"),
        "/Coze/Drive/简化画廊/minimax_tts_adapter.py",
    ]
    for p in candidates:
        p = os.path.normpath(p)
        if os.path.exists(p):
            spec = importlib.util.spec_from_file_location("minimax_tts_adapter", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _BACKENDS["minimax"] = mod
            return mod
    return None


_OPENAI_BASE = os.environ.get("TTS_OPENAI_BASE_URL", "").rstrip("/")
_OPENAI_KEY = os.environ.get("TTS_OPENAI_API_KEY", "")
_OPENAI_MODEL = os.environ.get("TTS_OPENAI_MODEL", "tts-1")
_EDGE_DEFAULT = os.environ.get("TTS_EDGE", "zh-CN-YunxiNeural")

# 各后端 voice_id 预设(键统一: male/female/child/narrator/warm/serious/default)
_VOICE_PRESET = {
    "edge": {
        "male": "zh-CN-YunxiNeural",
        "female": "zh-CN-XiaoxiaoNeural",
        "child": "zh-CN-XiaoyiNeural",
        "narrator": "zh-CN-YunfengNeural",
        "warm": "zh-CN-XiaoshuangNeural",
        "serious": "zh-CN-YunyangNeural",
        "default": "zh-CN-YunxiNeural",
    },
    "openai_compat": {
        "male": "alloy", "female": "nova", "child": "shimmer",
        "narrator": "onyx", "warm": "fable", "serious": "echo",
        "default": "alloy",
    },
}


def _resolve_voice_id(backend: str, voice_id: Optional[str],
                      character: Optional[str] = None) -> str:
    """解析 voice_id。minimax 交给 adapter(带角色映射); 其他用本地预设。"""
    if backend == "minimax":
        mod = _load_minimax_adapter()
        if mod and hasattr(mod, "resolve_voice_id"):
            return mod.resolve_voice_id(voice_id, character)
        return voice_id or "default"
    preset = _VOICE_PRESET.get(backend, {})
    return preset.get(voice_id or "default",
                      _EDGE_DEFAULT if backend == "edge" else "default")


def _provider_available(provider: str) -> bool:
    if provider == "edge":
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            return False
    if provider == "openai_compat":
        return bool(_OPENAI_KEY)
    if provider == "minimax":
        mod = _load_minimax_adapter()
        if mod is None:
            return False
        try:
            import minimax_client  # noqa: F401
            return True
        except Exception:
            return False
    return False


def _do_edge(text, voice_id, rate, pitch, out_path, character=None):
    import asyncio
    import edge_tts

    async def _run():
        tts = edge_tts.Communicate(text, _resolve_voice_id("edge", voice_id))
        with open(out_path, "wb") as f:
            async for chunk in tts.stream():
                if chunk.get("type") == "audio":
                    f.write(chunk.get("data", b""))
        return out_path

    try:
        asyncio.run(_run())
        return {"ok": True, "backend": "edge", "path": out_path,
                "audio_url": out_path, "voice_id": voice_id,
                "duration_ms": 0, "error": ""}
    except Exception as e:
        try:
            os.remove(out_path)
        except Exception:
            pass
        return {"ok": False, "backend": "edge", "path": out_path,
                "audio_url": "", "duration_ms": 0, "error": "edge-tts 网络合成失败: %s" % e}


def _do_openai(text, voice_id, out_path, response_format="mp3",
               emotion="neutral", speed=1.0):
    base = _OPENAI_BASE or "https://api.openai.com/v1"
    body = json.dumps({"model": _OPENAI_MODEL, "input": text,
                       "voice": voice_id or "alloy",
                       "response_format": response_format}).encode()
    req = urllib.request.Request(f"{base}/audio/speech", data=body,
        headers={"Authorization": f"Bearer {_OPENAI_KEY}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio_bytes = resp.read()
        if not audio_bytes:
            raise RuntimeError("OpenAI TTS 返回空音频")
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        return {"ok": True, "backend": "openai_compat", "path": out_path,
                "audio_url": out_path, "voice_id": voice_id,
                "duration_ms": 0, "error": ""}
    except Exception as e:
        return {"ok": False, "backend": "openai_compat", "path": out_path,
                "audio_url": "", "duration_ms": 0, "error": str(e)}


def _do_minimax(text, voice_id, out_path, emotion="neutral",
                speed=1.0, character=None):
    """MiniMax 主线。转调 minimax_tts_adapter; 无 adapter 时直接调 minimax_client。"""
    mod = _load_minimax_adapter()
    if mod:
        return mod.synthesize(text, voice_id=voice_id, emotion=emotion,
                              speed=speed, out_path=out_path,
                              backend="minimax", character=character)
    # 无 adapter 时直接调 minimax_client(若已导入)
    try:
        import minimax_client
        vid = _resolve_voice_id("minimax", voice_id, character)
        result = minimax_client.tts(text=text, voice_id=vid,
                                     speed=float(speed), emotion=emotion,
                                     out_path=out_path)
        if not result.get("ok"):
            return {"ok": False, "backend": "minimax", "path": out_path,
                    "duration_ms": 0, "voice_id": vid, "emotion": emotion,
                    "error": str(result.get("error", "MiniMax 合成失败"))}
        return {"ok": True, "backend": "minimax", "path": result.get("path", out_path),
                "duration_ms": int(result.get("duration_ms") or 0),
                "voice_id": vid, "emotion": emotion, "error": ""}
    except Exception as e:
        return {"ok": False, "backend": "minimax", "path": out_path,
                "duration_ms": 0, "voice_id": voice_id, "emotion": emotion,
                "error": f"minimax_client 不可用: {e}"}


def synthesize(text, voice="default", rate="+0%", pitch="+0Hz",
               out_path=None, provider="auto", response_format="mp3",
               tmp_dir="tts_out",
               # ---- 新签名(对齐 model_gateway audio_tts) ----
               voice_id: Optional[str] = None,
               emotion: str = "neutral",
               speed: float = 1.0,
               character: Optional[str] = None,
               backend: str = "") -> Dict[str, Any]:
    """单条合成。

    新签名: synthesize(text, voice_id, emotion, speed, out_path, backend, character)
    旧签名: synthesize(text, voice, rate, pitch, out_path, provider) 仍兼容。
    """
    # ---- 归一化后端 ----
    backend = backend or provider
    if backend in ("", "auto"):
        if _provider_available("minimax"):
            backend = "minimax"
        elif _provider_available("openai_compat"):
            backend = "openai_compat"
        elif _provider_available("edge"):
            backend = "edge"
        else:
            return {"ok": False, "backend": "none", "path": "",
                    "duration_ms": 0, "error":
                    "无可用 TTS 后端(minimax_client / TTS_OPENAI_API_KEY / edge-tts)"}
    # ---- 归一化 voice_id(旧 voice 参数兼容) ----
    if voice_id is None:
        voice_id = voice

    os.makedirs(tmp_dir, exist_ok=True)
    if out_path is None:
        out_path = os.path.join(tmp_dir, f"tts_{int(time.time()*1000)}.mp3")

    if backend == "minimax":
        return _do_minimax(text, voice_id, out_path, emotion=emotion,
                          speed=speed, character=character)
    elif backend == "openai_compat":
        if not _provider_available("openai_compat"):
            return {"ok": False, "backend": "openai_compat", "path": out_path,
                    "duration_ms": 0, "error":
                    "缺少 TTS_OPENAI_API_KEY / TTS_OPENAI_BASE_URL"}
        return _do_openai(text, voice_id, out_path, response_format,
                         emotion=emotion, speed=speed)
    elif backend == "edge":
        if not _provider_available("edge"):
            return {"ok": False, "backend": "edge", "path": out_path,
                    "duration_ms": 0, "error": "edge-tts 未安装:pip install edge-tts"}
        return _do_edge(text, voice_id, rate, pitch, out_path, character=character)
    else:
        return {"ok": False, "backend": backend, "path": out_path,
                "duration_ms": 0, "error": f"未知后端 {backend}"}


def list_voices(provider="edge", backend="") -> Dict[str, Any]:
    """查可用音色。backend=minimax 时拍平 system_voice + voice_cloning。"""
    backend = backend or provider
    if backend in ("", "auto"):
        if _provider_available("minimax"):
            backend = "minimax"
        elif _provider_available("openai_compat"):
            backend = "openai_compat"
        else:
            backend = "edge"
    if backend == "minimax":
        mod = _load_minimax_adapter()
        if mod and hasattr(mod, "list_voices"):
            return mod.list_voices(backend="minimax")
        return {"ok": False, "voices": [], "backend": "minimax",
                "error": "minimax_tts_adapter 不可用"}
    if backend == "edge":
        if not _provider_available("edge"):
            return {"ok": False, "voices": [], "backend": "edge",
                    "error": "edge-tts 未安装"}
        return {"ok": True, "backend": "edge",
                "voices": list(_VOICE_PRESET["edge"].values())}
    return {"ok": True, "backend": backend,
            "voices": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]}


def batch_synthesize(lines, voice="default", tmp_dir="tts_out", provider="auto",
                     voice_id=None, emotion="neutral", backend="",
                     out_dir=None, character=None) -> Dict[str, Any]:
    """批量合成。lines={line_id:text}, 落盘名用 line_id, 对齐分镜表。"""
    backend = backend or provider
    out_dir = out_dir or tmp_dir
    results = {}
    total_ms = 0
    ok_count = 0
    for line_id, text in lines.items():
        path = os.path.join(out_dir, f"line_{line_id}.mp3")
        r = synthesize(text, voice_id=voice_id or voice, emotion=emotion,
                       out_path=path, backend=backend, character=character,
                       tmp_dir=out_dir)
        results[line_id] = r
        if r.get("ok"):
            ok_count += 1
            total_ms += int(r.get("duration_ms") or 0)
    return {"ok": ok_count == len(lines) and len(lines) > 0,
            "results": results, "backend": backend,
            "ok_count": ok_count, "total_count": len(lines),
            "total_duration_ms": total_ms}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="声音轨 TTS(可插拔多后端)")
    p.add_argument("text")
    p.add_argument("--voice", default="default",
                   help="voice_id 或预设键(male/female/child/narrator/warm/serious)")
    p.add_argument("--character", default=None, help="角色名(沈临/苏雪晴), 自动映射")
    p.add_argument("--emotion", default="neutral",
                   choices=["neutral", "happy", "sad", "angry", "fearful",
                            "disgusted", "surprised"])
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--backend", default="auto",
                   choices=["auto", "minimax", "openai_compat", "edge"])
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    out = synthesize(args.text, voice_id=args.voice, emotion=args.emotion,
                     speed=args.speed, out_path=args.out,
                     backend=args.backend, character=args.character)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
