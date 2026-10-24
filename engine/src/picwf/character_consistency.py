# -*- coding: utf-8 -*-
"""character_consistency：角色一致性引擎（生成不偏移 / 精确 / 不走样 核心）。

痛点：现在 character_image 只回一个占位路径，分镜 prompt 不注入角色信息，
多集/多镜生成时角色脸、服装、气质必漂移。本模块做三件事：

1. build_character_block(char) -> 角色外观锁定描述块（中英双版本）
   锁 外貌/发型/服装/气质/年龄段，喂图生图 + 每镜文生图都注入，锚定角色不走样
2. build_three_view_prompt(char) -> 角色三视图（正/侧/背）参考图 prompt
   生成三视图做参考锚定（image 参考图 / LoRA 素材），后续每镜挂 reference
3. inject_into_shots(shots, chars) -> 把角色块注入每镜 prompt（带角色出场标记）

设计原则：角色块是"不可变外观基线"——一旦定稿，全片所有镜头共享同一份，
这是控一致性最稳的做法（不靠 LoRA 训练，靠描述锚定 + 参考图，兼容 1060 T1）。
"""
from typing import Dict, List, Any, Optional

# 角色默认外观基线（白皇短剧主角常见配置，可被 char dict 覆盖）
_DEFAULT_TRAIT = {
    "age_band": "25-32岁",
    "hair": "黑色中分微卷",
    "outfit": "简约都市通勤装",
    "temperament": "冷峻克制",
    "extra": "",
}


def _merged(char: Dict[str, Any]) -> Dict[str, Any]:
    m = dict(_DEFAULT_TRAIT)
    m.update({k: v for k, v in (char or {}).items() if v not in (None, "")})
    return m


def build_character_block(char: Dict[str, Any], lang: str = "bilingual") -> str:
    """生成角色外观锁定描述块。

    入参 char 可带: name/role(主角/反派/配角)/gender/age_band/hair/outfit/
    temperament/extra(特殊特征如泪痣、伤疤、眼镜)。
    返回稳定描述串：中英双版本（bilingual）/ 仅中(zh) / 仅英(en)。
    中英双版本是为了喂不同模型（1060 本地 SD1.5 吃中文+英文混合，FLUX/Seedream 吃英文）。
    """
    t = _merged(char)
    name = char.get("name", "角色")
    role = char.get("role", "主角")
    gender = char.get("gender", "女性" if "女" in (char.get("gender", "女") or "女") else "男性")

    zh = (f"{name}（{role}）：{gender}，{t['age_band']}，{t['hair']}，"
          f"{t['outfit']}，气质{t['temperament']}"
          + (f"，特征{t['extra']}" if t["extra"] else "") + "。"
          f"面部轮廓、五官比例、发型、服装配色全程保持一致。")
    en = (f"{name} ({role}): {gender} character, {t['age_band']}, {t['hair']}, "
          f"{t['outfit']}, {t['temperament']} demeanor"
          + (f", notable feature: {t['extra']}" if t["extra"] else "") + ". "
          f"Keep facial structure, proportions, hairstyle and outfit color consistent "
          f"across all shots.")
    if lang == "zh":
        return zh
    if lang == "en":
        return en
    return zh + " " + en


def build_three_view_prompt(char: Dict[str, Any]) -> str:
    """角色三视图参考图 prompt（正/侧/背），生成锚定参考图。

    用于 image 环节出角色设定图，后续每镜挂 reference 保持脸不走样。
    """
    t = _merged(char)
    name = char.get("name", "角色")
    block_en = build_character_block(char, lang="en")
    return (f"Character reference sheet of {name}, three views (front, side, back) "
            f"on neutral light-grey background, full body, consistent proportions, "
            f"clean studio lighting, 3:4 portrait layout. {block_en}")


def inject_into_shots(shots: List[Dict[str, Any]], chars: List[Dict[str, Any]],
                      appearance_hint: Optional[Dict[int, List[str]]] = None,
                      ) -> List[Dict[str, Any]]:
    """把角色外观块注入每镜 prompt，控一致性。

    shots: script_to_shots 产物里的 shots 列表（每项带 index/raw/prompt/shot_type...）。
    chars: 角色 dict 列表。appearance_hint: {shot_index: [role_name,...]} 指明该镜出场角色；
      不传时按"全部主角常驻 + 台词里提到的角色名出现"启发式判定。
    返回新 shots（不改原 list），每项新增 char_block 字段（注入后的完整 prompt）。
    """
    out = []
    blocks = {c.get("name", f"角色{i}"): build_character_block(c) for i, c in enumerate(chars)}
    all_names = list(blocks.keys())
    for sh in shots:
        idx = sh.get("index", 0)
        raw = sh.get("raw", "")
        if appearance_hint and idx in appearance_hint:
            present = [n for n in appearance_hint[idx] if n in blocks]
        else:
            # 启发式：台词里出现某角色名 -> 该角色出场；否则第一主角常驻
            present = [n for n in all_names if n and n in raw]
            if not present and all_names:
                present = [all_names[0]]
        block = " ".join(blocks[n] for n in present)
        new = dict(sh)
        new["char_block"] = block
        new["prompt"] = f"{new.get('prompt', '')} 角色基准：{block}".strip()
        new["present_chars"] = present
        out.append(new)
    return out


def three_view_anchor_refs(chars: List[Dict[str, Any]], workdir: str) -> List[Dict[str, str]]:
    """每个角色生成三视图参考图的落盘路径锚点（喂 image 环节 reference）。"""
    refs = []
    for c in chars:
        slug = str(c.get("name", "char")).replace(" ", "_")
        refs.append({"char": c.get("name", "char"),
                     "three_view_path": f"{workdir}/char_ref_{slug}_3view.png",
                     "prompt": build_three_view_prompt(c)})
    return refs
