# -*- coding: utf-8 -*-
"""成片真合成器：mock 占位 clips → ffmpeg 真拼接混音成片。

A 块最后一块：post_assemble 现在只输出路径占位，本模块把"成片真拼"落地——
  - mock 模式：comfyui_runner 没真跑时，用 ffmpeg 生成占位视频片段（纯色/渐变+
    文字水印），保证拼接链路可验证
  - 真模式：video_shot 已出真 clips 时，直接拼接
  - 音频轨：BGM/voice track 用 ffmpeg 生成占位音频（或接真音频文件），混音进成片
  - 输出：final_epN.mp4（真可播放 mp4）
ffmpeg 不可用时降级为占位路径（不阻塞管线）。
"""
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _gen_placeholder_clip(path: str, color: str, text: str,
                          duration_s: float = 2.0) -> bool:
    """ffmpeg 生成占位视频片段（纯色 + 文字水印）。"""
    if not ffmpeg_available():
        return False
    cmd = ["ffmpeg", "-y", "-f", "lavfi",
           "-i", f"color=c={color}:s=480x360:d={duration_s}",
           "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
           "-vf", f"drawtext=text='{text}':fontsize=24:fontcolor=white:x=20:y=20",
           "-shortest", "-pix_fmt", "yuv420p", path]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        return os.path.exists(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def _gen_placeholder_audio(path: str, freq: int = 440,
                           duration_s: float = 10.0) -> bool:
    """ffmpeg 生成占位音频轨（正弦波，代表 BGM/voice）。"""
    if not ffmpeg_available():
        return False
    cmd = ["ffmpeg", "-y", "-f", "lavfi",
           "-i", f"sine=frequency={freq}:sample_rate=44100",
           "-t", str(duration_s), "-acodec", "pcm_s16le", path]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
        return os.path.exists(path) and os.path.getsize(path) > 0
    except Exception:
        return False


def _probe_duration(path: str) -> float:
    if not os.path.exists(path):
        return 0.0
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration", "-of", "csv=p=0", path]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=15)
        return float(r.stdout.decode().strip() or 0)
    except Exception:
        return 0.0


def assemble(clips: List[str], audio_tracks: Optional[List[str]] = None,
             out_path: str = "", workdir: str = "",
             colors: Optional[List[str]] = None,
             shot_labels: Optional[List[str]] = None) -> Dict[str, Any]:
    """真·ffmpeg 合成：占位/真 clips + 音频轨 → 可播放成片 mp4。

    clips: 视频片段路径列表；若路径不存在则生成占位 clip（mock 模式）。
    audio_tracks: 音频轨路径列表（BGM/voice），缺省生成占位音频。
    out_path: 成片输出路径；缺省 workdir/final.mp4。
    返回 {ok, out, clip_count, duration_s, mode, ffmpeg}；
    ffmpeg 不可用 → {ok: False, ffmpeg: False, out: 占位路径}（不阻塞管线）。
    """
    workdir = workdir or os.path.dirname(out_path) or "."
    os.makedirs(workdir, exist_ok=True)
    out_path = out_path or os.path.join(workdir, "final.mp4")
    n = max(len(clips), 1)
    if not ffmpeg_available():
        # 降级：占位路径（管线仍可标记 publish_ready）
        return {"ok": False, "ffmpeg": False, "out": out_path,
                "clip_count": n, "mode": "placeholder_no_ffmpeg"}

    colors = colors or (["1E3A8A", "B91C1C", "4D7C0F", "7C3AED",
                         "B45309"] * max(1, (n // 5 + 1)))[:n]
    # 1) 准备视频片段（不存在的生成占位）
    final_clips: List[str] = []
    for i, c in enumerate(clips):
        label = (shot_labels[i] if shot_labels and i < len(shot_labels)
                 else f"shot_{i+1}")
        if c and os.path.exists(c) and os.path.getsize(c) > 0:
            final_clips.append(c)
        else:
            ph = os.path.join(workdir, f"_clip_{i+1:03d}.mp4")
            if _gen_placeholder_clip(ph, colors[i % len(colors)], label):
                final_clips.append(ph)
            else:
                final_clips.append("")  # 占位失败
    usable = [c for c in final_clips if c]
    if not usable:
        return {"ok": False, "ffmpeg": True, "out": out_path,
                "clip_count": 0, "mode": "clip_gen_failed"}

    # 2) 拼接视频
    concat_list = os.path.join(workdir, "_concat.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for c in usable:
            f.write(f"file '{c}'\n")
    concat_video = os.path.join(workdir, "_concat.mp4")
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
         "-c", "copy", concat_video], capture_output=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(concat_video):
        # concat 失败回退重编码拼接
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", concat_video],
            capture_output=True, timeout=120)
    if not os.path.exists(concat_video):
        return {"ok": False, "ffmpeg": True, "out": out_path,
                "clip_count": len(usable), "mode": "concat_failed"}

    # 3) 音频轨混音（缺省生成占位音频）
    audio_in: List[str] = []
    if audio_tracks:
        for a in audio_tracks:
            if a and os.path.exists(a) and os.path.getsize(a) > 0:
                audio_in.append(a)
    if not audio_in:
        ph_audio = os.path.join(workdir, "_bgm.wav")
        if _gen_placeholder_audio(ph_audio, freq=440,
                                  duration_s=_probe_duration(concat_video) or 6.0):
            audio_in.append(ph_audio)

    if audio_in:
        # 视频 + 第一条音频轨混音（多轨可后续扩展 amix）
        r = subprocess.run(
            ["ffmpeg", "-y", "-i", concat_video, "-i", audio_in[0],
             "-c:v", "copy", "-c:a", "aac", "-shortest", out_path],
            capture_output=True, timeout=60)
        if r.returncode != 0 or not os.path.exists(out_path):
            # 混音失败回退仅视频
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", concat_video, "-c:v", "copy",
                 "-c:a", "aac", out_path], capture_output=True, timeout=60)

    return {"ok": os.path.exists(out_path) and os.path.getsize(out_path) > 0,
            "ffmpeg": True, "out": out_path, "clip_count": len(usable),
            "duration_s": round(_probe_duration(out_path), 2),
            "audio_tracks": len(audio_in), "mode": "assembled"}
