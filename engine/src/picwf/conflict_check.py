"""四维冲突检测：画风 S × 音乐 M × 声音 V × BGM B 的组合合理性检查。
违和组合标 conflict 并给降级/替换建议，避免生硬硬配。
"""
from typing import Dict, List, Tuple

# 冲突矩阵（画风×音乐）：某画风配某音乐违和，给建议替换
STYLE_MUSIC_CONFLICT: Dict[str, Dict[str, List[str]]] = {
    "S1_anime_jp": {"M1_guoqin_classic": ["M28_anime_jpop","M4_rock_electric"], "M11_horror_drone": ["M12_suspense_strings","M20_ambient_space"]},
    "S8_dark_gothic": {"M13_funny_quirky": ["M27_haunting_gothic","M11_horror_drone"], "M30_corporate_soft": ["M27_haunting_gothic"]},
    "S9_cyberpunk": {"M1_guoqin_classic": ["M9_synthwave","M8_electronic_dance"], "M17_world_ethnic": ["M9_synthwave","M19_industrial"]},
    "S13_watercolor": {"M19_industrial": ["M25_classical_piano","M2_folk_guitar"], "M4_rock_electric": ["M25_classical_piano","M14_ballet_classical"]},
    "S18_cel_3d": {"M11_horror_drone": ["M13_funny_quirky","M30_corporate_soft"], "M27_haunting_gothic": ["M13_funny_quirky","M28_anime_jpop"]},
}
# 画风×BGM（场景功能违和）
STYLE_BGM_CONFLICT: Dict[str, Dict[str, List[str]]] = {
    "S18_cel_3d": {"B09_horror_deep": ["B07_daily_light","B34_cheer_merry"]},
    "S13_watercolor": {"B23_battle_full": ["B07_daily_light","B11_lyric_soft"], "B09_horror_deep": ["B11_lyric_soft","B12_ambience_bg"]},
    "S8_dark_gothic": {"B10_funny_relax": ["B08_suspense_cold","B28_tense_quiet"], "B34_cheer_merry": ["B27_despair_dark"]},
}

def check_conflict(style: str, music: str = "", voice: str = "", bgm: str = "") -> List[dict]:
    out: List[dict] = []
    if style and music:
        alt = STYLE_MUSIC_CONFLICT.get(style, {}).get(music)
        if alt:
            out.append({"axis": "style×music", "combo": f"{style}+{music}", "issue": "画风与音乐违和", "suggest": alt})
    if style and bgm:
        alt = STYLE_BGM_CONFLICT.get(style, {}).get(bgm)
        if alt:
            out.append({"axis": "style×bgm", "combo": f"{style}+{bgm}", "issue": "画风与BGM场景违和", "suggest": alt})
    # BGM 自带 music_ref，BGM与显式music冲突时（同情绪反向）粗检
    if music and bgm:
        _coarse_bgm_music(music, bgm, out)
    return out

def _coarse_bgm_music(music: str, bgm: str, out: List[dict]) -> None:
    # 极简粗检：BGM若标注music_ref与显式music同轴且情绪相反，提示
    # 这里保留扩展位，默认不强判
    pass

if __name__ == "__main__":
    print(check_conflict("S18_cel_3d", "M11_horror_drone", "", "B09_horror_deep"))
