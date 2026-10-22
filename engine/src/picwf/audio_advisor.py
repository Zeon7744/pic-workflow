"""audio_advisor：按剧种 × 场景功能智能裁剪音频轨生成（省心省事核心）。
auto 模式：只生成 scenario_resource_map 里该剧种的 default_tracks（1-2 条），省 50%+ 资源。
full 模式：生成 full_tracks（3 条全开），给精品剧/大场面。
"""
from typing import Dict, List

DEFAULT_SCENARIO = "light_comedy"

def advise_tracks(scenario: str, matrix: Dict, audio_mode: str = "auto",
                  ep: int = 1) -> List[Dict]:
    """返回推荐生成的音频轨节点配置列表（按优先级排序）。
    每条 = {id, name, impl, track_key, params, priority}
    """
    srm = matrix.get("scenario_resource_map", {})
    s = srm.get(scenario) or srm.get(DEFAULT_SCENARIO, {})
    tracks = s.get("full_tracks" if audio_mode == "full" else "default_tracks",
                   ["bgm"])

    result: List[Dict] = []
    for t in tracks:
        if t == "music":
            key = _pick_track_key(matrix, "emotion_arc_map", ep, "music", s.get("default_mood"))
            result.append({"id": "music", "name": f"音乐轨_{key}", "impl": "music_gen." + key,
                          "track_key": key, "priority": 1})
        elif t == "voice":
            key = _pick_track_key(matrix, "emotion_arc_map", ep, "voice", s.get("default_mood"))
            result.append({"id": "voice", "name": f"声音轨_{key}", "impl": "voice_tts." + key,
                          "track_key": key, "priority": 2})
        elif t == "bgm":
            key = s.get("default_bgm") or _pick_track_key(matrix, "emotion_arc_map", ep, "bgm", s.get("default_mood"))
            result.append({"id": "bgm", "name": f"背景轨_{key}", "impl": "bgm_mix." + key,
                          "track_key": key, "priority": 0})
    # 按 priority 排序：bgm 先（必配），music 次，voice 后
    result.sort(key=lambda x: x["priority"])
    return result

def _pick_track_key(matrix: Dict, arc_key: str, ep: int, dim: str, mood: str) -> str:
    """从 emotion_arc_map 按第 ep 集查对应 combo[dim]，查不到回退到 scenario default。"""
    arc = matrix.get(arc_key, {})
    for act in arc.values():
        if ep in act.get("episodes", []):
            combo = act.get("combo", {})
            if dim in combo:
                return combo[dim]
    # 回退到第一个 arc 的 combo
    if arc:
        first = next(iter(arc.values()))
        return first.get("combo", {}).get(dim, "")
    return ""
