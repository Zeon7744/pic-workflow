# -*- coding: utf-8 -*-
"""场景级配乐：按镜头段落换 BGM + 按时间点插特效音。

为什么不是「一首 BGM 铺到底」：
短剧一集里情绪是分段走的（施压 → 隐忍 → 反转），
单曲铺底会让反转毫无冲击力。这里按分镜段落切 BGM，并在关键节点插 SFX。
"""
import os
import shutil
import subprocess
from typing import Any, Dict, List

FFMPEG = shutil.which("ffmpeg")

# 分镜情绪/内容 → 素材文件名前缀（对应 05_音频/ 下的资产）
_EMO_ASSET = {
    "热血逆袭": ("我不做", "谁做", "反击", "打脸", "反转", "胜利", "抬头"),
    "情感铺垫": ("加班", "独自", "回忆", "疲惫", "流泪", "沉默"),
    "悬疑压迫": ("冷笑", "威胁", "坑你", "还不去", "甩到", "质问",
                 "紧张", "压迫", "冷静", "文件", "这个案子"),
}


def _probe(path: str) -> float:
    if not os.path.isfile(path):
        return 0.0
    r = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error",
                        "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float((r.stdout or "0").strip())
    except ValueError:
        return 0.0


def _seg_file(src: str, dst: str, dur: float, fade_s: float = 1.0) -> bool:
    """把素材循环裁切成 dur 秒，两端做淡化避免硬切。

    必须用 atrim 而不是只靠 -t：mp3 循环解码时 -t 按输出时间戳算，
    实际帧数会漂（实测 5.4s 的段做出 7.3s），四段拼起来整条床就短了 4 秒。
    """
    if not FFMPEG or dur <= 0.05:
        return False
    fade = min(fade_s, dur / 3.0)
    af = ("atrim=0:%.3f,asetpts=PTS-STARTPTS,"
          "afade=t=in:st=0:d=%.2f,afade=t=out:st=%.3f:d=%.2f,"
          "aresample=44100" % (dur, fade, max(0.0, dur - fade), fade))
    r = subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-stream_loop", "-1", "-i", src,
         "-t", "%.3f" % (dur + 0.5), "-af", af,
         "-c:a", "aac", "-b:a", "192k", dst],
        capture_output=True, timeout=180)
    return r.returncode == 0 and os.path.isfile(dst)


def build_scene_bed(segments: List[Dict[str, Any]], total_s: float,
                    out_path: str, workdir: str,
                    fade_s: float = 1.0) -> Dict[str, Any]:
    """segments: [{file, start_s, end_s}] → 拼成总长 total_s 的 BGM 床。

    段与段之间允许有空隙（用静音补齐），也允许首尾不对齐整片时长。
    """
    if not FFMPEG or not segments:
        return {"ok": False, "path": "", "error": "无 ffmpeg 或无段落"}
    os.makedirs(workdir, exist_ok=True)
    segs = sorted([s for s in segments if s.get("file") and os.path.isfile(s["file"])],
                  key=lambda x: float(x.get("start_s") or 0))
    if not segs:
        return {"ok": False, "path": "", "error": "段落素材都不存在"}

    parts: List[str] = []
    cursor = 0.0
    idx = 0
    for s in segs:
        st = max(0.0, float(s.get("start_s") or 0))
        en = float(s.get("end_s") or total_s)
        if st > cursor + 0.05:                       # 段前空隙补静音
            gap = st - cursor
            p = os.path.join(workdir, f"_bed_gap{idx}.m4a")
            if _silence(p, gap):
                parts.append(p)
            idx += 1
        dur = max(0.1, min(en, total_s) - max(st, cursor))
        p = os.path.join(workdir, f"_bed_seg{idx}.m4a")
        if _seg_file(s["file"], p, dur, fade_s):
            parts.append(p)
        cursor = max(st, cursor) + dur
        idx += 1

    if cursor < total_s - 0.05:                      # 尾部补静音
        p = os.path.join(workdir, "_bed_tail.m4a")
        if _silence(p, total_s - cursor):
            parts.append(p)

    if not parts:
        return {"ok": False, "path": "", "error": "段落拼接失败"}
    lst = os.path.join(workdir, "_bed_list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write("file '%s'\n" % os.path.abspath(p).replace("'", "'\\''"))
    raw = out_path + ".raw.m4a"
    r = subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c:a", "aac", "-b:a", "192k", raw],
                       capture_output=True, timeout=180)
    ok = r.returncode == 0 and os.path.isfile(raw)
    err = "" if ok else (r.stderr or "")[:200]
    # 兜底对齐：aac 每段都有编码 padding，拼接后会累积偏差。
    # 后期是按视频总长混音的，床短了尾部就没音乐、长了又会被 amix 拖长视频。
    if ok:
        r2 = subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", raw, "-af",
             "apad,atrim=0:%.3f,asetpts=PTS-STARTPTS" % total_s,
             "-c:a", "aac", "-b:a", "192k", out_path], capture_output=True, timeout=180)
        ok = r2.returncode == 0 and os.path.isfile(out_path)
        err = "" if ok else (r2.stderr or "")[:200]
    if os.path.isfile(raw):
        try:
            os.remove(raw)
        except OSError:
            pass
    return {"ok": ok, "path": out_path if ok else "",
            "duration_s": round(_probe(out_path), 2),
            "segments": len(parts), "error": err}


def _silence(dst: str, dur: float) -> bool:
    if dur <= 0.05:
        return False
    r = subprocess.run([FFMPEG, "-y", "-v", "error", "-f", "lavfi",
                        "-i", "anullsrc=r=44100:cl=stereo", "-t", "%.3f" % dur,
                        "-c:a", "aac", "-b:a", "192k", dst], capture_output=True, timeout=60)
    return r.returncode == 0 and os.path.isfile(dst)


def build_sfx_track(cues: List[Dict[str, Any]], total_s: float,
                    out_path: str, workdir: str) -> Dict[str, Any]:
    """cues: [{file, at_s, gain_db}] → 总长 total_s 的 SFX 轨（稀疏叠加）。"""
    if not FFMPEG or not cues:
        return {"ok": False, "path": "", "error": "无 ffmpeg 或无 cue"}
    valid = [c for c in cues if c.get("file") and os.path.isfile(c["file"])]
    if not valid:
        return {"ok": False, "path": "", "error": "cue 素材都不存在"}
    os.makedirs(workdir, exist_ok=True)

    args = [FFMPEG, "-y", "-v", "error"]
    for c in valid:
        args += ["-i", c["file"]]
    chains, labels = [], []
    for i, c in enumerate(valid):
        ms = int(max(0.0, float(c.get("at_s") or 0)) * 1000)
        g = float(c.get("gain_db") or 0.0)
        chains.append(f"[{i}:a]volume={g}dB,adelay={ms}|{ms}[s{i}]")
        labels.append(f"[s{i}]")
    # apad + atrim：保证混出来严格 total_s，否则 amix duration=longest 会被最长的 cue 拖长
    filt = (";".join(chains) + ";" + "".join(labels) +
            f"amix=inputs={len(valid)}:duration=longest:dropout_transition=0:normalize=0[m];"
            f"[m]apad,atrim=0:{total_s:.3f}[out]")
    args += ["-filter_complex", filt, "-map", "[out]",
             "-c:a", "aac", "-b:a", "192k", out_path]
    r = subprocess.run(args, capture_output=True, timeout=180)
    ok = r.returncode == 0 and os.path.isfile(out_path)
    return {"ok": ok, "path": out_path if ok else "",
            "cues": len(valid), "duration_s": round(_probe(out_path), 2),
            "error": "" if ok else (r.stderr or "")[:300]}


def auto_segments(shots: List[Dict[str, Any]], asset_map: Dict[str, str],
                  total_s: float) -> List[Dict[str, Any]]:
    """按分镜内容自动划分 BGM 段落。

    asset_map: {"悬疑压迫": 路径, "热血逆袭": 路径, "情感铺垫": 路径}
    相邻同场景段落会合并，避免频繁换曲。
    """
    if not shots or not asset_map:
        return []
    labels = []
    for s in shots:
        blob = str(s.get("raw") or "") + str(s.get("emotion") or "")
        hit = ""
        for name, kws in _EMO_ASSET.items():
            if name in asset_map and any(k in blob for k in kws):
                hit = name
                break
        labels.append(hit or (labels[-1] if labels else ""))
    labels = [l or "悬疑压迫" for l in labels]

    segs: List[Dict[str, Any]] = []
    cursor = 0.0
    for s, lab in zip(shots, labels):
        dur = float(s.get("est_s") or 5.4)
        if segs and segs[-1]["label"] == lab:
            segs[-1]["end_s"] = cursor + dur
        else:
            segs.append({"label": lab, "file": asset_map.get(lab, ""),
                         "start_s": cursor, "end_s": cursor + dur})
        cursor += dur
    return segs


def auto_cues(shots: List[Dict[str, Any]], segments: List[Dict[str, Any]],
              sfx_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """按段落切换点 / 情绪节点自动排 SFX。

    - 每个 BGM 段落切换点：转场音
    - 进入「热血逆袭」段：冲击音（打脸/反杀）
    - 进入「情感铺垫」段：压抑音
    """
    if not shots or not sfx_map:
        return []
    cues: List[Dict[str, Any]] = []
    trans = sfx_map.get("转场") or ""
    for i, seg in enumerate(segments):
        if i == 0:
            continue
        at = float(seg.get("start_s") or 0)
        lab = seg.get("label", "")
        if lab == "热血逆袭" and sfx_map.get("冲击"):
            cues.append({"file": sfx_map["冲击"], "at_s": at, "gain_db": -3.0})
        elif lab == "情感铺垫" and sfx_map.get("压抑"):
            cues.append({"file": sfx_map["压抑"], "at_s": at, "gain_db": -10.0})
        elif trans:
            cues.append({"file": trans, "at_s": at, "gain_db": -6.0})
    return cues
