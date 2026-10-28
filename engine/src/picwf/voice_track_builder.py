# -*- coding: utf-8 -*-
"""voice_track_builder — 从分镜表构建时间轴对齐的配音轨。

职责：
1. 从 shots 解析台词（角色 + 文本），过滤纯动作/旁白行
2. 调 voice_tts 按角色合成（不同角色不同音色）
3. 按镜头起始时间把每句台词放到正确位置（adelay），生成整集配音轨

设计要点：
- 台词必须落在对应镜头的时间点上，不能简单首尾相接，否则音画不同步
- 台词超长溢出到下一镜头时记录 warning，不阻断
- TTS 后端不可用时返回明确降级状态，不抛异常
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

# 角色名里常见的干扰（括号注释）
_PAREN = re.compile(r"[（(][^）)]*[）)]")
# 台词行：「角色：台词」或「角色:台词」
_LINE = re.compile(r"^([^\s：:，。！？、]{1,8})\s*[：:]\s*(.+)$")


def _clean(text: str) -> str:
    return _PAREN.sub("", text or "").strip()


def parse_line(raw: str) -> Optional[Dict[str, str]]:
    """解析一行台词。返回 {character, text, hint} 或 None（非台词行）。

    hint 是括号里的表演提示（冷笑/面无表情/抬头…），不朗读，但用于挑情绪。
    """
    src = raw or ""
    hints = _PAREN.findall(src)
    hint = " ".join(h.strip("（）() ") for h in hints).strip()
    s = _clean(src)
    if not s:
        return None
    m = _LINE.match(s)
    if not m:
        return None
    char, text = m.group(1).strip(), m.group(2).strip()
    # 过滤明显不是角色的情况（过长说明是叙述句）
    if len(char) > 6 or not text:
        return None
    # 排除以句号结尾的伪冒号（如 "他知道：这件事" 少见，忽略）
    return {"character": char, "text": text, "hint": hint}


def extract_lines(shots: List[Dict[str, Any]],
                  start_offset_s: float = 0.0) -> List[Dict[str, Any]]:
    """从 shots 提取台词，并算出每句在整集中的起始时间。

    shots 元素需含 raw / est_s / index（script_to_shots 产出结构）。
    """
    lines: List[Dict[str, Any]] = []
    t = start_offset_s
    for sh in shots or []:
        est = float(sh.get("est_s") or 5.4)
        parsed = parse_line(sh.get("raw", ""))
        if parsed:
            lines.append({
                "line_id": f"s{int(sh.get('index', 0)):03d}",
                "shot_index": int(sh.get("index", 0) or 0),
                "character": parsed["character"],
                "hint": parsed.get("hint", ""),
                "text": parsed["text"],
                "start_s": round(t, 3),
                "shot_est_s": est,
                "emotion": sh.get("emotion", "neutral"),
            })
        t += est
    return lines


def total_duration(shots: List[Dict[str, Any]], fallback: float = 0.0) -> float:
    d = sum(float(s.get("est_s") or 5.4) for s in (shots or []))
    return d if d > 0 else fallback


def _probe_duration(path: str) -> float:
    if not FFPROBE or not os.path.exists(path):
        return 0.0
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, timeout=30)
        return float((r.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


# 分镜情绪 -> TTS 情绪词（对齐 minimax adapter）
# script_to_shots 的 _classify_emotion 输出：反转/爆发/紧张/铺垫/推进
# 这里必须全覆盖，否则一律降级 neutral，等于丢掉表演差异。
_EMO_MAP = {
    "爆发": "angry", "反转": "surprised", "压抑": "sad", "沉淀": "neutral",
    "紧张": "fearful", "温情": "happy", "悲伤": "sad", "愤怒": "angry",
    "铺垫": "neutral", "推进": "neutral",
    "neutral": "neutral",
}

# 台词括号里的表演提示（原 parse_line 直接丢掉，白扔了最好的情绪信号）
_HINT_EMO = (
    ("冷笑", "angry"), ("嘲讽", "angry"), ("讥", "angry"), ("怒", "angry"),
    ("吼", "angry"), ("瞪", "angry"), ("咬牙", "angry"), ("质问", "angry"),
    ("面无表情", "neutral"), ("平静", "neutral"), ("淡淡", "neutral"),
    ("沉", "neutral"), ("停顿", "neutral"), ("顿", "neutral"),
    ("哽咽", "sad"), ("低声", "sad"), ("低头", "sad"), ("委屈", "sad"),
    ("哭", "sad"), ("叹气", "sad"), ("苦笑", "sad"),
    ("颤", "fearful"), ("害怕", "fearful"), ("紧张", "fearful"),
    ("犹豫", "fearful"), ("小心", "fearful"),
    ("惊讶", "surprised"), ("震惊", "surprised"), ("愣", "surprised"),
    ("笑", "happy"), ("微笑", "happy"), ("柔", "happy"), ("轻声", "happy"),
)


def _emotion_from_hint(hint: str) -> str:
    """括号提示 → 情绪。'' 表示没命中。"""
    h = hint or ""
    for kw, emo in _HINT_EMO:
        if kw in h:
            return emo
    return ""


# 性别+年龄 → VOICE_PRESET 键（adapter 再映射到 MiniMax 系统音色）
# 剧本角色名千变万化，靠 CHARACTER_PRESET 精确命中覆盖不了，必须按性别兜底。
def _pick_voice(character: str, characters: Optional[Dict[str, Any]] = None) -> str:
    c = (characters or {}).get(character or "") or {}
    g = str(c.get("gender") or "unknown").lower()
    try:
        age = int(c.get("age") or 0)
    except (TypeError, ValueError):
        age = 0
    if g == "female":
        return "serious" if age >= 32 else "female"
    if g == "male":
        return "male"
    # 推不出性别时用成年男声兜底：比童声/少女声更不容易出戏
    return "male"


def synthesize_lines(lines: List[Dict[str, Any]], out_dir: str,
                     backend: str = "", default_emotion: str = "neutral",
                     characters: Optional[Dict[str, Any]] = None
                     ) -> Dict[str, Any]:
    """逐句合成，按角色性别/年龄走不同 voice_id。返回每句的音频路径。"""
    from .cloud_api import voice_tts

    os.makedirs(out_dir, exist_ok=True)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for ln in lines:
        # 括号表演提示 > 分镜情绪字段 > 默认
        emo = (_emotion_from_hint(ln.get("hint", ""))
               or _EMO_MAP.get(str(ln.get("emotion", "")).strip(), "")
               or default_emotion)
        voice = _pick_voice(ln["character"], characters)
        out_path = os.path.join(out_dir, f"{ln['line_id']}.mp3")
        r = voice_tts.synthesize(
            ln["text"], out_path=out_path, backend=backend or "auto",
            emotion=emo, character=ln["character"], voice_id=voice,
        )
        item = dict(ln)
        item["emotion_used"] = emo
        item["voice_preset"] = voice
        item["ok"] = bool(r.get("ok"))
        item["path"] = r.get("path") or ""
        item["backend"] = r.get("backend") or ""
        item["duration_ms"] = int(r.get("duration_ms") or 0)
        item["error"] = r.get("error") or ""
        if item["ok"] and item["path"] and os.path.exists(item["path"]):
            item["duration_ms"] = item["duration_ms"] or int(
                _probe_duration(item["path"]) * 1000)
            results.append(item)
        else:
            failures.append(item)

    return {"ok": bool(results), "lines": results, "failures": failures,
            "synthesized": len(results), "failed": len(failures)}


def compose_track(lines: List[Dict[str, Any]], total_s: float,
                  out_path: str, workdir: str = "") -> Dict[str, Any]:
    """把已合成的台词按 start_s 放到静音底轨上，输出整集配音轨。"""
    usable = [ln for ln in lines
              if ln.get("path") and os.path.exists(ln["path"])]
    if not usable:
        return {"ok": False, "path": "", "error": "没有可用台词音频",
                "duration_s": 0.0, "line_count": 0}
    if not FFMPEG:
        return {"ok": False, "path": "", "error": "ffmpeg 不可用",
                "duration_s": 0.0, "line_count": len(usable)}

    total_s = max(total_s, max(
        ln["start_s"] + (ln.get("duration_ms") or 0) / 1000.0 for ln in usable))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)

    cmd: List[str] = [FFMPEG, "-y", "-v", "error",
                      "-f", "lavfi", "-i",
                      f"anullsrc=r=44100:cl=stereo:d={total_s:.3f}"]
    for ln in usable:
        cmd += ["-i", ln["path"]]

    parts: List[str] = []
    labels: List[str] = ["[0:a]"]
    for i, ln in enumerate(usable, start=1):
        delay_ms = int(round(ln["start_s"] * 1000))
        parts.append(
            f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}[v{i}]")
        labels.append(f"[v{i}]")

    parts.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:"
        f"normalize=0[out]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]",
            "-c:a", "libmp3lame", "-q:a", "2", out_path]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(out_path):
        err = (r.stderr or "").strip().splitlines()
        return {"ok": False, "path": "",
                "error": "配音轨合成失败: " + (" | ".join(err[-3:]) or "unknown"),
                "duration_s": 0.0, "line_count": len(usable)}

    return {"ok": True, "path": os.path.abspath(out_path),
            "duration_s": round(_probe_duration(out_path), 3),
            "line_count": len(usable)}


def build_voice_track(shots: List[Dict[str, Any]], out_path: str,
                      workdir: str = "", backend: str = "",
                      start_offset_s: float = 0.0,
                      characters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """一站式：shots -> 台词解析 -> 合成 -> 时间轴对齐拼接。"""
    lines = extract_lines(shots, start_offset_s=start_offset_s)
    if not lines:
        return {"ok": False, "path": "", "error": "分镜中未解析到台词行",
                "line_count": 0, "lines": [], "failures": [],
                "duration_s": 0.0}

    # 溢出检测：台词比所在镜头长
    syn = synthesize_lines(lines, workdir or os.path.dirname(out_path) or ".",
                           backend=backend, characters=characters)
    for ln in syn["lines"]:
        spare = ln["shot_est_s"] * 1000 - ln["duration_ms"]
        ln["overflow_ms"] = max(0, int(-spare))

    total_s = total_duration(shots)
    comp = compose_track(syn["lines"], total_s, out_path, workdir=workdir)

    return {
        "ok": bool(comp.get("ok")),
        "path": comp.get("path", ""),
        "error": comp.get("error", ""),
        "line_count": len(lines),
        "synthesized": syn["synthesized"],
        "failed": syn["failed"],
        "duration_s": comp.get("duration_s", 0.0),
        "timeline_s": round(total_s, 3),
        "lines": syn["lines"],
        "failures": syn["failures"],
        "overflow_lines": [l["line_id"] for l in syn["lines"] if l.get("overflow_ms")],
        "backend": (syn["lines"][0]["backend"] if syn["lines"] else ""),
    }


def main(argv=None) -> int:
    import argparse
    import json
    p = argparse.ArgumentParser(description="从分镜表构建配音轨")
    p.add_argument("--script", required=True, help="剧本 .md 路径")
    p.add_argument("--out", default="voice_ep1.mp3")
    p.add_argument("--workdir", default="./_voice_out")
    p.add_argument("--backend", default="")
    p.add_argument("--shots", type=int, default=10)
    a = p.parse_args(argv)

    from .pipeline_runner import script_to_shots
    text = open(a.script, encoding="utf-8").read()
    shots = script_to_shots(text, shots_per_ep=a.shots)["shots"]
    print(f"分镜数: {len(shots)}")
    r = build_voice_track(shots, a.out, workdir=a.workdir, backend=a.backend)
    brief = {k: r[k] for k in ("ok", "path", "line_count", "synthesized",
                               "failed", "duration_s", "timeline_s",
                               "overflow_lines", "backend", "error")}
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


__all__ = ["parse_line", "extract_lines", "total_duration",
           "synthesize_lines", "compose_track", "build_voice_track"]

if __name__ == "__main__":
    raise SystemExit(main())
