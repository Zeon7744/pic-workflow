# -*- coding: utf-8 -*-
"""shot_choreo：时间轴化分镜 + 单镜单运镜 + 时长反推动作量。

吸收 2026 公开前沿（Seedance 2 / 时间戳控制）比 ComfyUI 原生工作流更优的
突出点：

1. 时间轴化分镜：把一镜拆成 0-4s / 5-9s / 10-14s 时段，每段写
   "谁+在哪+做什么+镜头怎么动"，精确到秒（Seedance 2 对时间戳敏感）
2. 单镜单运镜 + 速度锁定：每镜只给 1 种运镜 + 明确"缓慢/快速"，
   避免"又要推又要摇模型打架"
3. 时长反推动作量：用 est_s 反推该镜能塞多少动作（10 秒只够
   "一个动作 + 一个情绪反应"），超出就建议拆镜
"""
from typing import Dict, List, Any, Optional

# 运镜类别（每镜单选）+ 速度词
_MOTION_SINGLE = {
    "固定": "（机位固定）",
    "推":   "（缓慢推近）",
    "拉":   "（缓慢后拉）",
    "摇":   "（横向摇移）",
    "移":   "（平稳横移）",
    "跟":   "（手持跟拍）",
    "环绕": "（360 环绕）",
    "甩":   "（急甩镜）",
}

# 时长段 → 推荐动作量（秒 → 动作数）
_SEC_ACTION_CAP = {5: 1, 8: 2, 12: 3, 15: 4}


def _action_cap(sec: float) -> int:
    """时长反推动作量上限（10 秒 → 最多 2 个动作）。"""
    caps = sorted(_SEC_ACTION_CAP.items())
    cap = caps[0][1]
    for s, c in caps:
        if sec >= s:
            cap = c
    return cap


def time_axis(segments: List[Dict[str, Any]]) -> str:
    """时间轴化分镜：把 "0-4s 谁在哪做什么" 片段拼成时间戳 prompt。

    segments: [{start_s, end_s, who, where, action, motion}]
    返回 "0-4s: ...; 5-9s: ...; ..." 时间轴串（喂 Seedance 2 / 可灵）。
    """
    out = []
    for seg in segments:
        s = int(seg.get("start_s", 0))
        e = int(seg.get("end_s", s + 4))
        body = " ".join(x for x in [
            seg.get("who", ""), seg.get("where", ""),
            seg.get("action", ""), _MOTION_SINGLE.get(seg.get("motion", ""), "")
        ] if x)
        out.append(f"{s}-{e}s: {body}".strip(": "))
    return "; ".join(out)


def single_motion_lock(motion: str, speed: str = "缓慢") -> str:
    """单镜单运镜 + 速度锁定（控模型不瞎推）。

    motion: 固定/推/拉/摇/移/跟/环绕/甩。speed: 缓慢/快速/急。
    返回 "缓慢推近" 这种单一运镜描述。
    """
    base = _MOTION_SINGLE.get(motion, "（机位固定）")
    label = f"{speed}{'推近' if motion=='推' else '后拉' if motion=='拉' else '横移' if motion in ('摇','移') else motion}"
    return label


def motion_consistency_audit(shot_prompts: List[str]) -> List[Dict[str, Any]]:
    """审计每镜 prompt 是否混入多种运镜（打架信号）。

    返回违规项：{index, found_motions, hint}。1 镜 > 1 种运镜 → 建议收敛。
    """
    motion_words = ["推", "拉", "摇", "移", "跟", "环绕", "甩", "固定"]
    violations = []
    for i, p in enumerate(shot_prompts):
        found = [m for m in motion_words if m in p]
        # 数不重复运镜（"推近""推拉"算 2 种）
        distinct = set()
        for m in motion_words:
            if m in p:
                distinct.add(m)
        # "推拉摇移" 同时出现算打架
        if len(distinct) >= 2:
            violations.append({
                "index": i + 1,
                "found_motions": sorted(distinct),
                "hint": f"第{i+1}镜混入 {len(distinct)} 种运镜，模型只能执行一种且容易打架，建议收敛到单一运镜",
            })
    return violations


def suggest_split(shot: Dict[str, Any]) -> Optional[str]:
    """时长反推动作量：超出该镜时长能容纳的动作量时，建议拆镜。

    shot 可带 est_s（镜时长）+ actions（该镜动作数）。返回建议拆镜说明，
    无拆建议返回 None。
    """
    est_s = float(shot.get("est_s", 5.4))
    actions = int(shot.get("actions", 1))
    cap = _action_cap(est_s)
    if actions <= cap:
        return None
    return (f"该镜 {est_s:.0f}s 只能容纳 {cap} 个动作，你安排了 {actions} 个，"
            f"建议拆成 {actions - cap + 1} 镜：前镜完成前 {cap} 个动作，后镜续接剩余动作。"
            f"用时长反推动作量，比写完再砍省时间。")


def craft_time_axis_shot(shot: Dict[str, Any], topic: str = "现实") -> Dict[str, Any]:
    """给单镜补时间轴化时段 + 单镜单运镜 + 时长反推校验（联动 prompt_craft）。

    返回新 shot（原字段保留 + time_axis + motion_locked + split_advice）。
    """
    est_s = float(shot.get("est_s", 5.4))
    # 默认把镜拆成 3 段（若 est_s < 6 则单段）
    if est_s < 6:
        segments = [{"start_s": 0, "end_s": int(est_s),
                     "who": shot.get("who", ""), "where": shot.get("scene", ""),
                     "action": shot.get("raw", ""), "motion": shot.get("motion", "固定")}]
    else:
        third = est_s / 3
        segments = [
            {"start_s": 0, "end_s": int(third),
             "who": shot.get("who", ""), "where": shot.get("scene", ""),
             "action": "进入/起始动作", "motion": shot.get("motion", "固定")},
            {"start_s": int(third), "end_s": int(third * 2),
             "who": shot.get("who", ""), "where": shot.get("scene", ""),
             "action": "主要动作", "motion": "固定"},
            {"start_s": int(third * 2), "end_s": int(est_s),
             "who": shot.get("who", ""), "where": shot.get("scene", ""),
             "action": "情绪反应 / 收", "motion": "固定"},
        ]
    return {
        **shot,
        "time_axis": time_axis(segments),
        "segments": segments,
        "motion_locked": single_motion_lock(shot.get("motion", "固定"),
                                              shot.get("motion_speed", "缓慢")),
        "split_advice": suggest_split(shot),
    }
