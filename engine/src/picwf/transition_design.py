# -*- coding: utf-8 -*-
"""transition_design：镜头转场设计引擎（行业前3的镜头语言层）。

continuity 管"角色/姿态不崩"，本模块管"镜头与镜头之间怎么切才顺"——
行业前3的 AI 短剧，镜头间不是硬切，而是按情绪/叙事选转场（硬切/叠化/
划像/匹配剪辑/甩镜/遮罩转场），并给出每处转场的"时长 + 触发理由 + 音效对位"。

本模块做三件事：
1. pick_transition(prev_shot, cur_shot, emotion_arc) -> 选一个转场类型 + 理由
2. plan_transitions(shots, emotion_arc) -> 给整段镜头排好转场方案（含时长/音效）
3. transition_qa(plan) -> 转场方案质检（连续两次同型转场/转场过密/与情绪不匹配 等）

转场类型（industry set）：
- hard_cut      硬切（快节奏/动作）
- cross_dissolve 叠化（情绪过渡/时间流逝）
- whip_pan      甩镜（快速切场景）
- match_cut     匹配剪辑（动作/构图匹配，高级手法）
- mask_wipe     遮罩转场（遮挡物过场）
- l_cut / j_cut 声音先入/后出（声音转场）
"""
from typing import Dict, List, Any, Optional

# 转场类型 -> 推荐时长(秒) + 适用情绪
_TRANSITION_META = {
    "hard_cut":       {"duration": 0.0,  "emotion": ["tense", "action", "reveal"], "sfx": "impact"},
    "cross_dissolve": {"duration": 0.8,  "emotion": ["melancholy", "dream", "warm", "romance"], "sfx": "soft_pad"},
    "whip_pan":       {"duration": 0.35, "emotion": ["action", "chase", "tense"], "sfx": "whoosh"},
    "match_cut":      {"duration": 0.0,  "emotion": ["action", "revelation", "symbolic"], "sfx": "none"},
    "mask_wipe":      {"duration": 0.5,  "emotion": ["neutral", "scene_change"], "sfx": "swish"},
    "l_cut":          {"duration": 0.0,  "emotion": ["neutral", "dialogue"], "sfx": "audio_in"},
    "j_cut":          {"duration": 0.0,  "emotion": ["neutral", "dialogue", "anticipation"], "sfx": "audio_out"},
}


def pick_transition(prev_shot: Dict[str, Any], cur_shot: Dict[str, Any],
                    emotion: str = "neutral") -> Dict[str, Any]:
    """在两镜之间选一个转场。

    规则（按优先级）：
    - 动作快切（prev/cur 都是 action 或 reveal）且同场景 -> hard_cut
    - 同场景同主体动作可衔接 -> match_cut（高级）
    - 场景突变（不同 scene）-> whip_pan（快）或 mask_wipe（中性）
    - 情绪是 melancholy/dream/warm/romance -> cross_dissolve
    - 台词镜之间 -> j_cut（声音先出）
    - 默认 hard_cut
    """
    p_act = prev_shot.get("action") or ""
    c_act = cur_shot.get("action") or ""
    p_scene = prev_shot.get("scene")
    c_scene = cur_shot.get("scene")
    same_scene = (p_scene == c_scene and p_scene)
    is_action = any(k in (p_act + c_act) for k in ["跑", "追", "打", "冲", "闪", "摔", "冲", "冲"])
    dialogue = any(k in (prev_shot.get("dialogue", "") + cur_shot.get("dialogue", "")) for k in ["「", "\""])

    if same_scene and is_action and emotion in ("tense", "action"):
        choice = "hard_cut"
    elif same_scene and p_act and c_act and p_act == c_act:
        choice = "match_cut"   # 同动作匹配剪辑
    elif not same_scene and emotion in ("action", "chase", "tense"):
        choice = "whip_pan"
    elif not same_scene:
        choice = "mask_wipe" if emotion in ("neutral", "scene_change") else "hard_cut"
    elif emotion in ("melancholy", "dream", "warm", "romance"):
        choice = "cross_dissolve"
    elif dialogue:
        choice = "j_cut"
    else:
        choice = "hard_cut"

    meta = _TRANSITION_META[choice]
    return {
        "from": prev_shot.get("index", 0),
        "to": cur_shot.get("index", 0),
        "type": choice,
        "duration": meta["duration"],
        "emotion_fit": emotion in meta["emotion"] or emotion == "neutral",
        "sfx": meta["sfx"],
        "reason": _reason(choice, prev_shot, cur_shot, emotion),
    }


def _reason(choice, prev, cur, emotion):
    why = {
        "hard_cut": "快节奏动作/同场景冲击，硬切保持张力",
        "match_cut": "同主体同动作匹配剪辑，高级衔接不穿帮",
        "whip_pan": "场景突变 + 动作情绪，甩镜快速过场不拖节奏",
        "mask_wipe": "场景切换中性，遮罩过场柔和不突兀",
        "cross_dissolve": "情绪性过渡（慢/暖/梦），叠化留白呼应情绪",
        "l_cut": "声音先入铺陈下一镜，空间感衔接",
        "j_cut": "台词声音先出，镜头后跟，保持对话流畅",
    }
    return why[choice]


def plan_transitions(shots: List[Dict[str, Any]],
                    emotion_arc: List[str] = None) -> List[Dict[str, Any]]:
    """给整段镜头排转场方案。

    emotion_arc: 每镜对应的情绪（长度 >= len(shots)-1 时按 index 取，否则 neutral）。
    返回 [{from, to, type, duration, sfx, reason, emotion_fit}]。
    """
    n = len(shots)
    if n < 2:
        return []
    plan = []
    for i in range(1, n):
        em = "neutral"
        if emotion_arc and i - 1 < len(emotion_arc):
            em = emotion_arc[i - 1] if i - 1 < len(emotion_arc) else "neutral"
        plan.append(pick_transition(shots[i - 1], shots[i], em))
    return plan


def transition_qa(plan: List[Dict[str, Any]]) -> Dict[str, Any]:
    """转场方案质检：找"行业前3"标准下的转场问题。

    检查：
    - 连续两次同型非 hard_cut 转场（视觉疲劳）
    - 5 秒内转场次数 > 4（过密）
    - 情绪不匹配的转场（emotion_fit=False）
    返回 {issues:[...], density_max, passed}。
    """
    issues = []
    prev_type = None
    run_start = 0
    for i, tr in enumerate(plan):
        # 连续同型（排除 hard_cut，硬切连用是正常节奏）
        if tr["type"] == prev_type and tr["type"] != "hard_cut":
            issues.append({"kind": "repeat_transition", "at": tr["to"],
                          "detail": f"第{tr['to']}镜连续两次 {tr['type']}，视觉疲劳，建议插入 hard_cut 破节奏"})
        prev_type = tr["type"]
        # 情绪不匹配
        if not tr.get("emotion_fit", True):
            issues.append({"kind": "emotion_mismatch", "at": tr["to"],
                          "detail": f"第{tr['to']}镜 {tr['type']} 与当前情绪不完全匹配，可复核"})
    # 转场密度：累计时长窗口
    acc, window = 0.0, 5.0
    density_max = 0
    seg_count = 0
    for tr in plan:
        acc += tr.get("duration", 0.0)
        seg_count += 1
        if acc >= window:
            density_max = max(density_max, seg_count)
            issues.append({"kind": "over_dense", "at": tr["to"],
                          "detail": f"第{tr['to']}镜前 5 秒内 {seg_count} 个转场，节奏过密"})
            acc, seg_count = 0.0, 0
    return {"issues": issues, "density_max": density_max,
            "passed": not any(i["kind"] in ("repeat_transition", "over_dense") for i in issues)}
