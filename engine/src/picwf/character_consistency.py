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


# ============ 强化：特征词逐字锁定 + 质检帧人脸相似度 ============

# 模糊词黑名单（模型眼里"长发" vs "及腰长发"是两回事，差一个字脸就飘）
_VAGUE_WORDS = [
    ("长发", "及腰/及肩/齐耳 长发（写死长度）"),
    ("短发", "寸头/齐耳/齐眉 短发（写死长度）"),
    ("年轻", "精确年龄段（如 25-30 岁）"),
    ("好看", "具体五官（如 窄脸/圆脸 + 眼型 + 眉形）"),
    ("漂亮", "具体五官 + 肤质"),
    ("高", "精确身高（如 175cm）"),
    ("矮", "精确身高（如 160cm）"),
    ("瘦", "精确体型（如 偏瘦/标准/微胖）"),
    ("粗", "精确体型"),
    ("白", "精确肤色（如 冷白/暖白/小麦色）"),
    ("黑", "精确肤色（如 小麦色/古铜色/黝黑）"),
]


def lock_char_traits(char: Dict[str, Any]) -> Dict[str, Any]:
    """特征词逐字锁定：把模糊外貌词替换成精确写法。

    返回 {char, fixes:[{field, before, after}], locked:{...}}。
    公开前沿："长发" 和 "及腰长发" 模型眼里是两回事，差一个字脸就飘。
    """
    fixes = []
    locked = dict(char or {})
    for field in ["hair", "outfit", "age_band", "height", "build", "skin", "temperament"]:
        val = str(locked.get(field, ""))
        for vague, precise in _VAGUE_WORDS:
            if vague in val:
                fixes.append({"field": field, "before": val, "after": val.replace(vague, precise)})
                val = val.replace(vague, precise)
        locked[field] = val
    return {"char": char, "fixes": fixes, "locked": locked,
            "locked_block": build_character_block(locked) if char.get("name") else ""}


def face_similarity_gate(ref_face: str, frame_faces: List[Dict[str, Any]],
                         threshold: float = 0.65) -> Dict[str, Any]:
    """质检帧人脸相似度打分入口（第三道锁）。

    ref_face: 角色卡正脸参考（路径或 embedding 列表，本函数只接 embedding）。
    frame_faces: 每帧裁出的脸 [{frame_idx, face_embed, ...}]。
    threshold: 相似度阈值（公开前沿 0.65，低于进重渲染队列）。
    返回 {below_threshold:[frame_idx], avg_score, passed}。
    embedding 缺省时按 0 分处理（触发人工核对）。
    """
    ref_emb = None
    if isinstance(ref_face, list) and ref_face:
        ref_emb = ref_face
    below, scores = [], []
    for ff in frame_faces:
        if ref_emb is None:
            score = 0.0
        else:
            emb = ff.get("face_embed")
            if emb is None:
                score = 0.0
            else:
                # 简化：cosine 相似度（本函数不依赖 numpy，做标量归一）
                try:
                    import math
                    dot = sum(a * b for a, b in zip(ref_emb, emb))
                    na = math.sqrt(sum(a * a for a in ref_emb)) or 1
                    nb = math.sqrt(sum(b * b for b in emb)) or 1
                    score = dot / (na * nb)
                except Exception:
                    score = 0.0
        scores.append(score)
        if score < threshold:
            below.append(ff.get("frame_idx", len(below)))
    avg = sum(scores) / len(scores) if scores else 0.0
    return {"below_threshold": below, "avg_score": round(avg, 4),
            "passed": not below, "re_render_queue": below}


def three_view_anchor_refs(chars: List[Dict[str, Any]], workdir: str) -> List[Dict[str, str]]:
    """每个角色生成三视图参考图的落盘路径锚点（喂 image 环节 reference）。"""
    refs = []
    for c in chars:
        slug = str(c.get("name", "char")).replace(" ", "_")
        refs.append({"char": c.get("name", "char"),
                     "three_view_path": f"{workdir}/char_ref_{slug}_3view.png",
                     "prompt": build_three_view_prompt(c)})
    return refs
