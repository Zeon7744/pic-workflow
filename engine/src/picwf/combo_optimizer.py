"""combo_optimizer：四维协同优化器（S/M/V/B 按情绪弧线打分，输出最优 + 次优组合）。
精准命中核心：跨维度协同打分，不再 4 维独立选。
"""
from typing import Dict, List, Tuple

# 权重：画风情绪匹配 40% / 音乐场景匹配 30% / 声音角色匹配 15% / BGM 功能匹配 15%
W = {"style": 0.40, "music": 0.30, "voice": 0.15, "bgm": 0.15}

def optimize(scenario: str, ep: int, matrix: Dict) -> Dict:
    """返回 {best: combo, alt: combo, scores: {best_score, alt_score}, reason}"""
    arc = matrix.get("emotion_arc_map", {})
    # 找 ep 对应的 act
    act = None
    for a in arc.values():
        if ep in a.get("episodes", []):
            act = a
            break
    if not act:
        # ep 超范围，回退到 act5
        act = arc.get("act5_ending", next(iter(arc.values()), None))
        if not act:
            return {"best": {}, "alt": {}, "scores": {}, "reason": "no emotion_arc_map in matrix"}

    best_combo = dict(act.get("combo", {}))
    alt_combo = dict(act.get("combo_alt", {}))
    # 打分（按 scenario 的 mood 微调）
    srm = matrix.get("scenario_resource_map", {})
    scenario_cfg = srm.get(scenario, {})
    mood = scenario_cfg.get("default_mood", "")

    best_score = _score_combo(best_combo, mood, matrix)
    alt_score = _score_combo(alt_combo, mood, matrix)
    # 如果 alt 比 best 分高，交换
    if alt_score > best_score:
        best_combo, alt_combo = alt_combo, best_combo
        best_score, alt_score = alt_score, best_score

    return {
        "best": best_combo,
        "alt": alt_combo,
        "scores": {"best_score": round(best_score, 3), "alt_score": round(alt_score, 3)},
        "reason": f"episode={ep} scenario={scenario} mood={mood}",
    }

def _score_combo(combo: Dict, mood: str, matrix: Dict) -> float:
    """四维协同打分（0-100）。mood 影响权重微调：匹配度 ± 10 分。"""
    if not combo:
        return 0.0
    s = 0.0
    for dim, w in W.items():
        key = combo.get(dim, "")
        if not key:
            continue
        # 每个维度基础分 = w * 80（默认匹配）
        base = w * 80
        # mood 匹配微调：combo[dim] 的 label 与 mood 文本接近时 +10*w，否则 -5*w
        label = _track_label(matrix, dim, key)
        bonus = 10 if _mood_match(label, mood) else (-5 if mood else 0)
        s += base + w * bonus
    return s / 100 * 100  # 归一到 0-100

def _track_label(matrix: Dict, dim: str, key: str) -> str:
    block = {"style": "style_tracks", "music": "music_tracks",
             "voice": "voice_tracks", "bgm": "bgm_tracks"}[dim]
    return matrix.get(block, {}).get(key, {}).get("label", key)

def _mood_match(label: str, mood: str) -> bool:
    """简单文本匹配：label 里出现 mood 关键词（或其同义）算匹配。"""
    if not mood:
        return False
    mood_aliases = {
        "热血": ["热血", "燃", "爆发", "战斗", "高燃"],
        "甜蜜": ["甜", "浪漫", "温馨", "治愈"],
        "紧张": ["紧张", "悬疑", "压迫", "冷峻", "惊悚"],
        "宏大": ["史诗", "宏大", "悲壮", "荣耀", "辉煌"],
        "忧伤": ["忧伤", "悲伤", "虐", "催泪", "离别"],
        "轻快": ["轻快", "搞笑", "俏皮", "日常", "欢快"],
        "冷峻": ["冷峻", "科幻", "赛博", "冷"],
        "燃": ["燃", "热血", "爆发"],
        "温情": ["温情", "治愈", "团聚", "温暖"],
        "向上": ["成长", "蜕变", "向上", "希望"],
    }
    for kw in mood_aliases.get(mood, [mood]):
        if kw in label:
            return True
    return False
