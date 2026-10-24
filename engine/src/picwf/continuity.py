# -*- coding: utf-8 -*-
"""continuity：镜头间首尾帧传递 + 骨架先锁再注角色。

公开前沿反复强调这是"同一个人不崩"的第一道锁。ComfyUI 原生工作流
只做单镜生成，镜头间的连续性靠人工。本模块做：

1. 骨架先锁：每镜先传"姿态/位置/运动方向"（上一镜结尾 -> 下一镜开头），
   再注入角色外观块。顺序不能反，反了角色就漂。
2. 首尾帧传递：上一镜尾帧（pose + position + facing）作为下一镜的
   初始条件（first_frame 参考）。
3. 换装检测：服装变化时整批替换服装块，保留发型/配饰等不变特征
   （公开前沿"服装一致性"要点）。
4. 镜头链验证：检测姿态/位置在镜头链里是否连续（瞬移信号）。

设计：给一镜 shots 列表，逐镜把"上镜结尾状态"作为"本镜开头状态"传下去，
并在 prompt 里显式标注"承接自上一镜：{pose} {facing}"。
"""
from typing import Dict, List, Any, Optional


def lock_skeleton_first(shot: Dict[str, Any],
                        prev_state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """骨架先锁再注角色：把上镜结尾姿态作为本镜开头。

    shot 可带: pose / position / facing / outfit_change（bool 换装）。
    prev_state: 上一镜的 {pose, position, facing, outfit}。
    返回新 shot（原字段保留 + carry_from_prev + skeleton_locked 标记）。
    """
    new = dict(shot)
    if prev_state:
        new["carry_from_prev"] = {
            "pose": prev_state.get("pose", "站立"),
            "position": prev_state.get("position", ""),
            "facing": prev_state.get("facing", ""),
        }
        # 关键：prompt 里显式承接
        inherit = f"承接自上一镜：{new['carry_from_prev']['pose']}，位置 {new['carry_from_prev']['position'] or '延续'}，朝向 {new['carry_from_prev']['facing'] or '延续'}"
        new["prompt"] = f"{inherit}；{new.get('prompt', '')}".strip("；")
    new["skeleton_locked"] = True
    return new


def chain_shots(shots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """镜头链首尾帧传递：逐镜把上镜 state 传到下镜。

    每镜需带 state_after（本镜结尾的状态）：{pose, position, facing, outfit}。
    返回新 shots，每项带 carry_from_prev + skeleton_locked。
    """
    out: List[Dict[str, Any]] = []
    prev: Optional[Dict[str, Any]] = None
    for sh in shots:
        locked = lock_skeleton_first(sh, prev)
        out.append(locked)
        # 本镜结尾状态 -> 下镜开头（换装检测）
        state_after = sh.get("state_after") or {}
        if sh.get("outfit_change") and prev and prev.get("outfit"):
            # 换装：服装整批替换，但发型/配饰继承
            state_after = dict(state_after)
            state_after["outfit_note"] = f"换装：{state_after.get('outfit', '新服装')}；保留发型/配饰 {prev.get('outfit', '')}"
        prev = state_after or prev
    return out


def outfit_change_audit(shots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """换装点检测：标注哪些镜发生了服装变化。

    返回 [{index, from_outfit, to_outfit, note}]。换装后镜头整批
    替换服装块，其他特征（发型/配饰）继承不变。
    """
    out = []
    prev_outfit = None
    for i, sh in enumerate(shots):
        cur = sh.get("outfit")
        if sh.get("outfit_change") or (cur and prev_outfit and cur != prev_outfit):
            out.append({
                "index": i + 1, "from_outfit": prev_outfit or "",
                "to_outfit": cur or "",
                "note": f"第{i+1}镜换装，服装整批替换；保留发型/配饰不变",
            })
        prev_outfit = cur
    return out


def teleport_audit(shots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """瞬移信号检测：同场景镜头间位置/朝向跳变。

    连续镜头场景相同但位置突然变化 → 建议插入过渡镜。
    返回违规 [{index, prev_position, curr_position, hint}]。
    """
    out = []
    for i in range(1, len(shots)):
        prev, cur = shots[i - 1], shots[i]
        if (prev.get("scene") and cur.get("scene")
                and prev.get("scene") == cur.get("scene")
                and prev.get("position") and cur.get("position")
                and prev["position"] != cur["position"]
                and not cur.get("transition")):
            out.append({
                "index": i + 1,
                "prev_position": prev["position"],
                "curr_position": cur["position"],
                "hint": f"第{i+1}镜同场景位置从 {prev['position']} 跳到 {cur['position']}，"
                        f"缺过渡镜会瞬移，建议插入一个运动过渡",
            })
    return out


def apply_character_after_skeleton(shots: List[Dict[str, Any]],
                                   chars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """骨架锁完后才注角色（顺序严格：骨架 -> 角色）。

    公开前沿：先锁骨架再注入角色，顺序不能反（反了角色就漂）。
    调 character_consistency.inject_into_shots，但只在 skeleton_locked 之后跑。
    """
    from .character_consistency import inject_into_shots
    if not all(s.get("skeleton_locked") for s in shots):
        raise ValueError("必须先经 chain_shots 锁骨架再注角色（顺序不能反）")
    return inject_into_shots(shots, chars)
