# -*- coding: utf-8 -*-
"""multimodal_qa：多模态深度质检引擎（行业前3的音画同步层）。

qa_loop 是"产物齐不齐"的基础质检（5 项缺口），本模块是"音画对不对"的深度质检——
行业前3 的 AI 短剧出片后还要过：口型对齐、音画同步、节奏卡点、BGM 情绪匹配。

不依赖外部模型（纯规则 + 数值对齐，可离线跑），四个质检维度：
1. lip_sync_qa -> 口型对齐：台词时间戳 vs 嘴部动帧 偏差是否在阈值内
2. av_sync_qa   -> 音画同步：音频事件时间 vs 对应画面帧 偏移
3. rhythm_qa    -> 节奏卡点：动作/转折是否卡在 BGM 节拍点上
4. emotion_align_qa -> 情绪对齐：BGM 情绪标签 vs 画面情绪 是否匹配
每个返回 {passed, issues:[...], score}，并给 aggregate_multimodal_qa 汇总。
"""
from typing import Dict, List, Any, Optional

# 行业阈值（可被入参覆盖）
LIP_SYNC_TOL_S = 0.12      # 口型偏差容忍（120ms，行业可感知上限）
AV_SYNC_TOL_S = 0.20       # 音画同步容忍（200ms）
RHYTHM_SNIPE_TOL_S = 0.30  # 卡点偏移容忍（300ms）


def lip_sync_qa(lip_events: List[Dict[str, Any]],
                tol_s: float = LIP_SYNC_TOL_S) -> Dict[str, Any]:
    """口型对齐质检。

    lip_events: [{t, offset_s}]，t=台词时间戳，offset_s=嘴部动帧相对台词的偏差。
    偏差 > tol 的进 issues。返回 {passed, issues, score, max_offset}。
    score = 1 - (超限帧数 / 总帧数)。
    """
    if not lip_events:
        return {"passed": True, "issues": [], "score": 1.0, "max_offset": 0.0,
                "note": "无口型事件，跳过"}
    issues, bad = [], 0
    max_off = 0.0
    for ev in lip_events:
        off = abs(float(ev.get("offset_s", 0.0)))
        max_off = max(max_off, off)
        if off > tol_s:
            bad += 1
            issues.append({"t": ev.get("t"), "offset_s": round(off, 3),
                          "detail": f"t={ev.get('t')}s 口型偏移 {off:.3f}s > 阈值 {tol_s}s"})
    score = round(1.0 - bad / len(lip_events), 3)
    return {"passed": bad == 0, "issues": issues, "score": score,
            "max_offset": round(max_off, 3), "checked": len(lip_events)}


def av_sync_qa(audio_events: List[Dict[str, Any]],
               tol_s: float = AV_SYNC_TOL_S) -> Dict[str, Any]:
    """音画同步质检：音频事件（打击/喊声/门声）与其画面帧的对齐。

    audio_events: [{t, offset_s, label}]，offset_s=音频相对画面动作的偏移。
    """
    if not audio_events:
        return {"passed": True, "issues": [], "score": 1.0, "note": "无音画事件"}
    issues, bad = [], 0
    for ev in audio_events:
        off = abs(float(ev.get("offset_s", 0.0)))
        if off > tol_s:
            bad += 1
            issues.append({"label": ev.get("label", ""), "t": ev.get("t"),
                          "offset_s": round(off, 3),
                          "detail": f"'{ev.get('label','')}' 音画偏移 {off:.3f}s > {tol_s}s"})
    score = round(1.0 - bad / len(audio_events), 3)
    return {"passed": bad == 0, "issues": issues, "score": score, "checked": len(audio_events)}


def rhythm_qa(action_marks: List[Dict[str, Any]], beat_times: List[float],
              tol_s: float = RHYTHM_SNIPE_TOL_S) -> Dict[str, Any]:
    """节奏卡点质检：关键动作/转折是否卡在 BGM 节拍点。

    action_marks: [{t}] 关键时刻（如"拔刀""反转揭晓"）。
    beat_times: BGM 的节拍点时间序列。
    每个 action 找最近节拍点，偏移 > tol 进 issues。
    """
    if not action_marks:
        return {"passed": True, "issues": [], "score": 1.0, "note": "无卡点动作"}
    if not beat_times:
        return {"passed": False, "issues": [{"kind": "no_beat"}], "score": 0.0,
                "detail": "有卡点动作但无 BGM 节拍，节奏失控"}
    issues, bad, snaps = [], 0, []
    for am in action_marks:
        t = float(am.get("t", 0.0))
        # 最近节拍
        nearest = min(beat_times, key=lambda b: abs(b - t))
        off = abs(nearest - t)
        snaps.append({"t": t, "nearest_beat": round(nearest, 3), "offset_s": round(off, 3)})
        if off > tol_s:
            bad += 1
            issues.append({"t": t, "nearest_beat": round(nearest, 3), "offset_s": round(off, 3),
                          "detail": f"t={t}s 动作偏离最近节拍 {off:.3f}s > {tol_s}s，建议卡点"})
    score = round(1.0 - bad / len(action_marks), 3)
    return {"passed": bad == 0, "issues": issues, "score": score, "snaps": snaps,
            "checked": len(action_marks)}


def emotion_align_qa(shot_emotions: List[Dict[str, Any]],
                    bgm_emotions: List[str]) -> Dict[str, Any]:
    """情绪对齐质检：每镜画面情绪 vs 当时 BGM 情绪标签。

    shot_emotions: [{t, emotion}]。bgm_emotions: [{t, emotion}] BGM 情绪段。
    找每镜 t 对应的 BGM 情绪段，不匹配进 issues（不阻断，仅提示）。
    """
    if not shot_emotions or not bgm_emotions:
        return {"passed": True, "issues": [], "score": 1.0, "note": "缺情绪数据"}
    # 构建 BGM 情绪时间轴
    segs = sorted(bgm_emotions, key=lambda x: x.get("t", 0))
    issues, mismatch = [], 0
    for sh in shot_emotions:
        t = float(sh.get("t", 0.0))
        # 找 t 所在段（最后一个 start<=t）
        cur = None
        for s in segs:
            if s.get("t", 0) <= t:
                cur = s
        if cur is not None and sh.get("emotion") and cur.get("emotion") and sh.get("emotion") != cur.get("emotion"):
            # 允许情绪"近似"（warm/romance 视为一组，tense/action 一组）
            groups = {("warm", "romance"), ("tense", "action", "chase")}
            a, b = sh.get("emotion"), cur.get("emotion")
            if not any(g for g in groups if a in g and b in g):
                mismatch += 1
                issues.append({"t": t, "shot": sh.get("emotion"), "bgm": cur.get("emotion"),
                              "detail": f"t={t}s 画面情绪 {sh.get('emotion')} vs BGM {cur.get('emotion')} 不匹配"})
    score = round(1.0 - mismatch / len(shot_emotions), 3)
    return {"passed": mismatch == 0, "issues": issues, "score": score, "checked": len(shot_emotions)}


def aggregate_multimodal_qa(lip: Dict, av: Dict, rhythm: Dict, emotion: Dict,
                            weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """汇总四个维度的多模态质检分。

    weights: 各维度权重（默认 口型0.4 / 音画0.3 / 卡点0.2 / 情绪0.1）。
    返回 {score, passed, dims:{...}, blocking}。blocking=任一核心维(口型/音画)不过。
    """
    w = {"lip": 0.4, "av": 0.3, "rhythm": 0.2, "emotion": 0.1}
    if weights:
        w.update(weights)
    dims = {
        "lip": lip.get("score", 0.0), "av": av.get("score", 0.0),
        "rhythm": rhythm.get("score", 0.0), "emotion": emotion.get("score", 0.0),
    }
    total_w = sum(w.values()) or 1.0
    score = round(sum(dims[k] * w[k] for k in dims) / total_w, 3)
    blocking = (not lip.get("passed", True)) or (not av.get("passed", True))
    return {
        "score": score, "passed": not blocking, "blocking": blocking,
        "dims": dims, "weights": w,
        "detail": {k: {"passed": x.get("passed"), "issues": len(x.get("issues", []))}
                  for k, x in [("lip", lip), ("av", av), ("rhythm", rhythm), ("emotion", emotion)]},
    }
