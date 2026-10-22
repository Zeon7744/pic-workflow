"""四维冲突检测（升级版）：画风 S × 音乐 M × 声音 V × BGM B 的组合合理性。
v2：从 0/1 违和 → 0-100 适配分矩阵；high=推荐 / mid=可用 / low=违和。
"""
from typing import Dict, List, Optional

# 冲突矩阵（画风×音乐）：key = (S, M)，value = 适配分 0-100（<40 标违和）
STYLE_MUSIC_FIT: Dict[str, Dict[str, int]] = {
    "S1_anime_jp":     {"M1_guoqin_classic": 30, "M11_horror_drone": 20, "M28_anime_jpop": 95, "M4_rock_electric": 85},
    "S8_dark_gothic":  {"M13_funny_quirky": 10, "M27_haunting_gothic": 90, "M11_horror_drone": 80},
    "S9_cyberpunk":    {"M1_guoqin_classic": 15, "M9_synthwave": 95, "M8_electronic_dance": 85},
    "S13_watercolor":  {"M19_industrial": 10, "M25_classical_piano": 90, "M2_folk_guitar": 80},
    "S18_cel_3d":      {"M11_horror_drone": 15, "M13_funny_quirky": 90, "M30_corporate_soft": 80},
    "S20_photoreal_8k":{"M5_classical_orch": 85, "M25_classical_piano": 90, "M1_guoqin_classic": 40},
}

STYLE_BGM_FIT: Dict[str, Dict[str, int]] = {
    "S18_cel_3d":      {"B09_horror_deep": 10, "B07_daily_light": 90, "B34_cheer_merry": 85},
    "S13_watercolor":  {"B23_battle_full": 10, "B11_lyric_soft": 90, "B07_daily_light": 80},
    "S8_dark_gothic":  {"B10_funny_relax": 15, "B08_suspense_cold": 90, "B27_despair_dark": 80},
    "S9_cyberpunk":    {"B12_ambience_bg": 85, "B28_tense_quiet": 80, "B07_daily_light": 30},
}

THRESHOLDS = {"high": 80, "mid": 50, "low": 0}  # >=80 推荐 / 50-79 可用 / <50 违和

def check_conflict(style: str, music: str = "", voice: str = "", bgm: str = "") -> List[dict]:
    """返回冲突告警列表。每条 = {axis, combo, score, level, suggest}。
    level: high/mid/low；low 时附 suggest 替换建议。
    """
    out: List[dict] = []
    if style and music:
        fit = STYLE_MUSIC_FIT.get(style, {}).get(music, 60)  # 未知组合默认 60（mid 可用）
        out.append(_mk("style×music", f"{style}+{music}", fit,
                       _suggest_alt(STYLE_MUSIC_FIT, style, music)))
    if style and bgm:
        fit = STYLE_BGM_FIT.get(style, {}).get(bgm, 60)
        out.append(_mk("style×bgm", f"{style}+{bgm}", fit,
                       _suggest_alt(STYLE_BGM_FIT, style, bgm)))
    # 过滤：只保留 level != "high" 的告警（high 不告警）
    return [c for c in out if c["level"] in ("mid", "low")]

def _mk(axis: str, combo: str, score: int, suggest: List[str]) -> dict:
    if score >= THRESHOLDS["high"]:
        level = "high"
    elif score >= THRESHOLDS["mid"]:
        level = "mid"
    else:
        level = "low"
    return {"axis": axis, "combo": combo, "score": score, "level": level,
            "suggest": suggest if level == "low" else []}

def _suggest_alt(fit_matrix: Dict[str, Dict[str, int]], style: str, bad_key: str) -> List[str]:
    """找该 style 下适配分最高的 top-2 key（排除 bad_key 本身）。"""
    rows = fit_matrix.get(style, {})
    if not rows:
        return []
    ranked = sorted(rows.items(), key=lambda x: -x[1])
    return [k for k, _ in ranked[:2] if k != bad_key]
