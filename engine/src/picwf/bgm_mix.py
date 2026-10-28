# -*- coding: utf-8 -*-
"""bgm_mix — 背景音乐/配乐与对白轨的混音（含对白闪避 ducking）。

职责边界：
- music_gen 负责"造音乐"（规格 + 生成）
- voice_tts  负责"造人声"
- bgm_mix    负责"把音轨合到一起"，并在对白期间自动压低 BGM

依赖：ffmpeg / ffprobe。缺失时优雅降级，不抛异常。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# 默认混音参数：对白存在时 BGM 压到 -14dB，对白结束 300ms 内恢复
DEFAULT_DUCK_DB = -14.0
DEFAULT_ATTACK_MS = 15
DEFAULT_RELEASE_MS = 300


def available() -> bool:
    """ffmpeg/ffprobe 是否可用。"""
    return bool(FFMPEG and FFPROBE)


def probe_duration(path: str) -> float:
    """返回音频时长(秒)，失败返回 0.0。"""
    if not FFPROBE or not os.path.exists(path):
        return 0.0
    try:
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30, check=True,
        )
        data = json.loads(out.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0.0



def _dur_s(music_like: List[str], inputs: Dict[str, str]) -> float:
    """取音乐类输入里最长的时长(秒)，用于侧链 apad 对齐。"""
    durs = [probe_duration(inputs[k]) for k in music_like if k in inputs]
    durs = [d for d in durs if d > 0]
    return max(durs) if durs else 600.0


def _db_to_volume(db: float) -> float:
    """dB 转线性增益。"""
    return 10.0 ** (db / 20.0)


def mix(voice_path: Optional[str] = None,
        bgm_path: Optional[str] = None,
        music_path: Optional[str] = None,
        out_path: str = "mix_out.mp3",
        duck_db: float = DEFAULT_DUCK_DB,
        bgm_gain_db: float = -6.0,
        music_gain_db: float = -12.0,
        attack_ms: int = DEFAULT_ATTACK_MS,
        release_ms: int = DEFAULT_RELEASE_MS,
        normalize: bool = True) -> Dict[str, Any]:
    """把对白 + BGM + 配乐混成一条音轨。

    Args:
        voice_path: 对白轨（同时也是 ducking 的触发源）
        bgm_path:   背景氛围轨（长循环，会被 ducking 压低）
        music_path: 主题配乐轨（叠加，音量更低）
        out_path:   输出路径
        duck_db:    对白期间 BGM 相对压低多少 dB（负值）
        bgm_gain_db / music_gain_db: 各自基础增益
        attack_ms / release_ms: 闪避的起落速度
        normalize:  是否做响度归一（loudnorm）

    Returns:
        {"ok", "path", "duration_ms", "inputs", "duck_db", "error"}
    """
    inputs: Dict[str, str] = {}
    for name, p in (("voice", voice_path), ("bgm", bgm_path), ("music", music_path)):
        if p and os.path.exists(p):
            inputs[name] = p

    if not inputs:
        return {"ok": False, "path": "", "duration_ms": 0, "inputs": {},
                "duck_db": duck_db,
                "error": "没有任何可用输入音轨（路径不存在或未提供）"}

    if not available():
        return {"ok": False, "path": "", "duration_ms": 0, "inputs": inputs,
                "duck_db": duck_db,
                "error": "ffmpeg/ffprobe 不可用，无法混音"}

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    has_voice = "voice" in inputs
    music_like = [k for k in ("bgm", "music") if k in inputs]

    # ---- 构造 filter_complex ----
    cmd: List[str] = [FFMPEG, "-y", "-v", "error"]
    idx: Dict[str, int] = {}
    for i, (name, p) in enumerate(inputs.items()):
        cmd += ["-i", p]
        idx[name] = i

    filters: List[str] = []
    labels: List[str] = []

    # 1) 对白轨：直接作为 ducking 的 sidechain 源 + 混音源
    n_music = len(music_like)
    if has_voice:
        vi = idx["voice"]
        # asplit = 1 路混音 + N 路侧链（每条音乐轨各需一份独立侧链）
        sc_labels = "".join(f"[sk{i}]" for i in range(n_music))
        filters.append(
            f"[{vi}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
            f"asplit={n_music + 1}[vs]{sc_labels}")
        labels.append("[vs]")

    # 2) 音乐类轨：先调基础增益，再（若有对白）挂 sidechaincompress
    for name in music_like:
        mi = idx[name]
        gain_db = bgm_gain_db if name == "bgm" else music_gain_db
        gain = _db_to_volume(gain_db)
        chain = (f"[{mi}:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo,"
                 f"volume={gain:.4f}")
        if has_voice:
            pad_dur = _dur_s(music_like, inputs)
            # duck_db 决定压缩强度：压得越深，ratio 越大
            # ~1.5dB per ratio unit, 夹在 [2, 20] 之间（2 为几乎不压）
            ratio = max(2.0, min(20.0, abs(duck_db) / 1.5))
            # threshold 约 -30dB：正常对白电平即可触发闪避
            thr = 0.03
            # 关键：侧链必须 apad 到与音乐轨等长，否则 sidechaincompress
            # 会在最后一句对白结束时截断 BGM（整集后段静音）
            chain += (f"[{name}g]")
            filters.append(chain)
            si = music_like.index(name)
            filters.append(
                f"[sk{si}]apad=whole_dur={pad_dur:.3f}[skp{si}]")
            filters.append(
                f"[{name}g][skp{si}]sidechaincompress="
                f"threshold={thr}:ratio={ratio:.2f}:"
                f"attack={attack_ms}:release={release_ms}"
                f":knee=2.0:level_sc=1[{name}d]")
            labels.append(f"[{name}d]")
        else:
            chain += f"[{name}d]"
            filters.append(chain)
            labels.append(f"[{name}d]")

    # 3) 混合
    n = len(labels)
    weights = " ".join(["1"] * n)
    filters.append(f"{''.join(labels)}amix=inputs={n}:duration=longest:"
                   f"weights={weights}:normalize=0[mixed]")
    final = "[mixed]"
    if normalize:
        filters.append("[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[out]")
        final = "[out]"

    cmd += ["-filter_complex", ";".join(filters), "-map", final,
            "-c:a", "libmp3lame", "-q:a", "2", out_path]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok": False, "path": "", "duration_ms": 0, "inputs": inputs,
                "duck_db": duck_db, "error": "混音超时(>600s)"}

    if r.returncode != 0 or not os.path.exists(out_path):
        err = (r.stderr or "").strip().splitlines()
        return {"ok": False, "path": "", "duration_ms": 0, "inputs": inputs,
                "duck_db": duck_db,
                "error": "ffmpeg 失败: " + (" | ".join(err[-3:]) or "unknown")}

    dur = probe_duration(out_path)
    return {"ok": True, "path": os.path.abspath(out_path),
            "duration_ms": int(dur * 1000), "inputs": inputs,
            "duck_db": duck_db,
            "duck_ratio": round(max(2.0, min(20.0, abs(duck_db) / 1.5)), 2),
            "error": ""}


def mix_episode(voice_tracks: Optional[Dict[str, str]] = None,
                bgm_path: Optional[str] = None,
                music_path: Optional[str] = None,
                out_dir: str = "mix_out",
                ep: int = 1,
                **kwargs: Any) -> Dict[str, Any]:
    """按集混音：voice_tracks 是 {line_id: 音频路径}，先拼对白再混 BGM。

    返回 {"ok", "path", "duration_ms", "voice_concat", "error"}
    """
    voice_tracks = voice_tracks or {}
    os.makedirs(out_dir, exist_ok=True)

    voice_concat = ""
    if voice_tracks:
        ordered = [voice_tracks[k] for k in sorted(voice_tracks)
                   if os.path.exists(voice_tracks[k])]
        if len(ordered) == 1:
            voice_concat = ordered[0]
        elif len(ordered) > 1:
            voice_concat = os.path.join(out_dir, f"ep{ep:02d}_voice.mp3")
            lst = os.path.join(out_dir, f"ep{ep:02d}_voice.txt")
            with open(lst, "w", encoding="utf-8") as f:
                for p in ordered:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            r = subprocess.run(
                [FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", lst, "-c:a", "libmp3lame", "-q:a", "2", voice_concat],
                capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                err = (r.stderr or "").strip().splitlines()
                return {"ok": False, "path": "", "duration_ms": 0,
                        "voice_concat": "",
                        "error": "对白拼接失败: " + (" | ".join(err[-2:]) or "unknown")}

    out_path = os.path.join(out_dir, f"ep{ep:02d}_mix.mp3")
    r = mix(voice_path=voice_concat or None, bgm_path=bgm_path,
            music_path=music_path, out_path=out_path, **kwargs)
    r["voice_concat"] = voice_concat
    r["ep"] = ep
    return r


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="BGM 混音（含对白闪避）")
    p.add_argument("--voice", default=None, help="对白轨")
    p.add_argument("--bgm", default=None, help="背景氛围轨")
    p.add_argument("--music", default=None, help="主题配乐轨")
    p.add_argument("--out", default="mix_out.mp3", help="输出路径")
    p.add_argument("--duck-db", type=float, default=DEFAULT_DUCK_DB)
    p.add_argument("--no-normalize", action="store_true")
    a = p.parse_args(argv)

    print("ffmpeg 可用:", available())
    r = mix(voice_path=a.voice, bgm_path=a.bgm, music_path=a.music,
            out_path=a.out, duck_db=a.duck_db, normalize=not a.no_normalize)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


__all__ = ["available", "probe_duration", "mix", "mix_episode",
           "DEFAULT_DUCK_DB"]

if __name__ == "__main__":
    raise SystemExit(main())
