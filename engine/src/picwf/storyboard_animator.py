# -*- coding: utf-8 -*-
"""把静态分镜图变成动态片段（animatic / 动态分镜）。

为什么需要它：
Agnes 视频（agnes-video-2.5-flash）免费档队列常年满，额度档又不够，
短剧项目不能因此卡死。图像生成（agnes-image-*-flash）是免费且可用的，
所以先用「真实分镜图 + 缓慢推拉/平移」产出动态分镜：
- 画面是真实 AI 生成的，不是测试图案
- 时长严格对齐分镜 est_s，能与配音轨同步
- 后续视频配额可用时，只要把本环节换成真实视频，链路完全一致
"""
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# 镜头语言 → zoompan 表达式（z=缩放，x/y=取景原点）
# 系数 0.0008/帧 @30fps ≈ 5 秒放大约 12%，接近真实缓慢推轨
_MOTIONS = {
    "push_in":  ("min(zoom+0.0009,1.18)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pull_out": ("if(eq(on,1),1.18,max(zoom-0.0009,1.0))",
                 "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
    "pan_left": ("1.12", "max(0,(iw-iw/zoom)*(1-on/{frames}))", "ih/2-(ih/zoom/2)"),
    "pan_right": ("1.12", "min((iw-iw/zoom), (iw-iw/zoom)*on/{frames})", "ih/2-(ih/zoom/2)"),
    "tilt_up": ("1.12", "iw/2-(iw/zoom/2)", "max(0,(ih-ih/zoom)*(1-on/{frames}))"),
    "tilt_down": ("1.12", "iw/2-(iw/zoom/2)", "min((ih-ih/zoom),(ih-ih/zoom)*on/{frames})"),
    "still": ("1.0", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
}

# 分镜景别 → 运镜（景别越大越适合推，特写适合慢推或静帧）
_SHOT_MOTION = {
    "远景": "pan_right", "全景": "push_in", "中景": "push_in",
    "近景": "push_in", "特写": "push_in", "空镜": "pull_out",
}


def pick_motion(shot_type: str = "", index: int = 0) -> str:
    """按景别选运镜；不同镜头轮换，避免整集全是同一个动作。"""
    m = _SHOT_MOTION.get((shot_type or "").strip())
    if m:
        if m == "push_in" and index % 3 == 2:
            return "pull_out"
        return m
    return ("push_in", "pan_right", "pull_out", "pan_left")[index % 4]


def animate_still(src: str, out_path: str, duration_s: float,
                  motion: str = "push_in", w: int = 720, h: int = 1280,
                  fps: int = 30) -> Dict[str, Any]:
    """单张静图 → 指定时长的动态片段。"""
    if not src or not os.path.isfile(src):
        return {"ok": False, "path": "", "error": f"图片不存在: {src}"}
    if not FFMPEG:
        return {"ok": False, "path": "", "error": "ffmpeg 不可用"}
    dur = max(0.5, float(duration_s or 3.0))
    frames = max(1, int(dur * fps))
    z, x, y = _MOTIONS.get(motion, _MOTIONS["push_in"])
    x = x.format(frames=frames)
    y = y.format(frames=frames)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    # 先放大再 zoompan：直接在原尺寸上 zoom 会有明显抖动
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
          f"crop={w * 2}:{h * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
          f"setsar=1")
    cmd = [FFMPEG, "-y", "-v", "error", "-loop", "1", "-i", src,
           "-t", "%.3f" % dur, "-vf", vf,
           "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-an", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not os.path.isfile(out_path):
        return {"ok": False, "path": "", "error": f"ffmpeg 失败: {(r.stderr or '')[:300]}"}
    return {"ok": True, "path": out_path, "motion": motion,
            "duration_s": round(_probe(out_path), 3), "error": ""}


def _probe(path: str) -> float:
    if not FFPROBE or not os.path.isfile(path):
        return 0.0
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float((r.stdout or "0").strip())
    except ValueError:
        return 0.0
