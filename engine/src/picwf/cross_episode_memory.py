# -*- coding: utf-8 -*-
"""cross_episode_memory：跨集长期角色/世界观一致性引擎（行业前3能力）。

单集内的一致性靠 character_consistency（三视图 + 人脸相似度），
但 10 集、20 集的短剧里，角色第 1 集和第 10 集的脸/服装/气质还会漂——
因为每集独立出片，中间没有"长期记忆"把它们锚在一起。

本模块做三件事：
1. build_episode_anchor(ep) -> 本集"角色状态基线"快照（脸 embedding / 服装 / 发型 / 气质 / 场景）
2. anchor_gap_audit(prev_anchor, cur_anchor) -> 跨集漂移检测（哪些特征偏离了长期基线）
3. build_long_term_bible(chars, episodes) -> 角色圣经（全剧统一的外观基线 + 逐集演化轨迹），
   喂回 character_consistency，让后续每集都以圣经为准，不从"上一集"漂起

设计原则：
- 用"基线 vs 逐集快照"做漂移检测，不靠模型自由发挥
- 圣经是不可变权威源，逐集只能"演化"（如第 12 集主角发型变了 → 显式记录为 change，不是漂移）
- 演化是"显式声明"，漂移是"未声明"，两者分开——行业前3控一致性的核心
"""
from typing import Dict, List, Any, Optional

# 哪些特征是"长期锚定不可变"的（脸/骨架/气质），哪些允许"显式演化"（发型/服装）
_IMMUTABLE = ["face_emb", "skeleton", "temperament", "age_band"]
_EVOLVABLE = ["hair", "outfit", "expression", "injury"]


def build_episode_anchor(char_state: Dict[str, Any], ep: int,
                         explicit_changes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构建某集某角色的"状态快照"锚点。

    char_state: 本集实际生成用的角色 dict（含 face_emb/face 描述 + 发型/服装/气质...）。
    explicit_changes: 本集"有意"的特征变化（如 第5集主角染发），声明了的不算漂移。
    返回 {ep, char, snapshot, explicit}。
    """
    changes = explicit_changes or {}
    snap = {k: char_state.get(k) for k in
            ["face_emb", "skeleton", "temperament", "age_band", "hair", "outfit", "expression", "injury", "height"]}
    snap = {k: v for k, v in snap.items() if v is not None}
    return {"ep": ep, "char": char_state.get("name", "char"),
            "snapshot": snap, "explicit": changes}


def anchor_gap_audit(prev_anchor: Dict[str, Any], cur_anchor: Dict[str, Any],
                     face_sim_fn=None, face_threshold: float = 0.65) -> Dict[str, Any]:
    """跨集漂移检测：prev 集锚点 -> cur 集锚点，找出未声明的偏离。

    face_sim_fn: 可选的人脸相似度函数 (emb_a, emb_b) -> [0,1]；
      缺省时若两边都有 face_emb 且相等视为 1.0，否则 0.0。
    返回 {drifts:[{field, prev, cur, severity}], stable:[...],
          declared_changes, face_score, is_drift}。
    severity: 不可变特征漂 = "critical"；可变特征漂（未声明）= "warning"。
    """
    ps, cs = prev_anchor.get("snapshot", {}), cur_anchor.get("snapshot", {})
    declared = cur_anchor.get("explicit", {}) or {}
    drifts, stable = [], []

    # 人脸
    face_score = 1.0
    if "face_emb" in ps and "face_emb" in cs:
        if face_sim_fn is not None:
            face_score = float(face_sim_fn(ps.get("face_emb"), cs.get("face_emb")))
        else:
            face_score = 1.0 if ps.get("face_emb") == cs.get("face_emb") else 0.0
    if face_score < face_threshold:
        drifts.append({"field": "face", "prev": "<emb>", "cur": "<emb>",
                       "severity": "critical", "detail": f"face sim {face_score:.2f} < {face_threshold}"})
    else:
        stable.append("face")

    for k in ["hair", "outfit", "expression", "injury", "temperament", "skeleton", "age_band"]:
        pv, cv = ps.get(k), cs.get(k)
        if pv is None and cv is None:
            continue
        if pv == cv:
            stable.append(k)
        else:
            if k in declared:
                # 显式演化，不算漂移
                stable.append(f"{k}(declared)")
            else:
                sev = "critical" if k in _IMMUTABLE else "warning"
                drifts.append({"field": k, "prev": pv, "cur": cv, "severity": sev})

    return {
        "drifts": drifts, "stable": stable,
        "declared_changes": sorted(declared.keys()),
        "face_score": round(face_score, 4),
        "is_drift": any(d["severity"] == "critical" for d in drifts),
        "episode_gap": cur_anchor.get("ep", 0) - prev_anchor.get("ep", 0),
    }


def build_long_term_bible(chars: List[Dict[str, Any]],
                          episode_anchors: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成全剧"角色圣经"：每个角色的不可变基线 + 显式演化轨迹。

    chars: 角色 dict 列表。episode_anchors: 逐集 build_episode_anchor 的结果（按 ep 升序）。
    返回 {bible:{char:{base, evolution:[{ep, field, from, to}]}}, consistency_note}。
    base = 第 1 集快照（权威基线），evolution = 从基线到当前发生过的"显式"特征变化。
    """
    bible: Dict[str, Dict[str, Any]] = {}
    # 按角色分组逐集锚点
    by_char: Dict[str, List[Dict[str, Any]]] = {}
    for a in episode_anchors:
        by_char.setdefault(a["char"], []).append(a)
    for c in chars:
        name = c.get("name", "char")
        eps = sorted(by_char.get(name, []), key=lambda x: x.get("ep", 0))
        if not eps:
            # 没快照就用角色卡做基线
            base = {k: c.get(k) for k in ["face_emb", "skeleton", "temperament", "age_band", "hair", "outfit"] if c.get(k) is not None}
            bible[name] = {"base": base, "evolution": [], "anchor_count": 0}
            continue
        base = dict(eps[0].get("snapshot", {}))
        evolution = []
        for i in range(1, len(eps)):
            prev_s, cur_s = eps[i - 1].get("snapshot", {}), eps[i].get("snapshot", {})
            declared = eps[i].get("explicit", {}) or {}
            for field, new_v in cur_s.items():
                old_v = prev_s.get(field)
                if new_v != old_v and field in declared:
                    evolution.append({"ep": eps[i].get("ep"), "field": field,
                                      "from": old_v, "to": new_v})
        bible[name] = {"base": base, "evolution": evolution, "anchor_count": len(eps)}
    bible_order = [c.get("name", "char") for c in chars]
    return {
        "bible": bible, "char_order": bible_order,
        "consistency_note": "以 bible.base 为不可变权威；跨集生成时注入 base，"
                           "逐集 evolution 里声明过的字段才允许随集变化",
    }


def inject_bible_into_episodes(bible: Dict[str, Any],
                               episode_char_states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把角色圣经注入后续每集的角色 state，保证从"基线"起而不从"上一集"漂起。

    episode_char_states: 每集的角色 dict 列表（每项带 ep）。
    返回修正后的逐集状态：不可变字段强制 = bible.base，可变字段若该集未声明演化则回填 base。
    """
    out = []
    for st in episode_char_states:
        name = st.get("name")
        entry = bible.get("bible", {}).get(name)
        new = dict(st)
        if entry:
            base = entry.get("base", {})
            # 不可变特征：始终对齐基线
            for k in _IMMUTABLE:
                if base.get(k) is not None:
                    new[k] = base[k]
            # 可变特征：本集未声明变化的，回填基线，避免累积漂移
            declared_this = st.get("_explicit_changes", {}) or {}
            for k in _EVOLVABLE:
                if k in base and k not in declared_this:
                    new[k] = base[k]
        out.append(new)
    return out
