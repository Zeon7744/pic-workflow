# -*- coding: utf-8 -*-
"""narrative_architect：集级叙事结构编排（短剧「爽点密度」引擎的前置）。

设计定位
--------
仓库里已有三类相邻能力，本模块不与它们重叠：
  * ``shot_choreo``   —— 单镜怎么拍（时间轴 / 单运镜 / 动作量）
  * ``transition_design`` —— 镜与镜之间怎么接（转场选型 / 疲劳质检）
  * ``multimodal_qa`` —— 成片出来之后查不查得过（口型 / 音画 / 卡点）

缺的一层是「整集怎么排」：开场几秒用什么钩子、爽点落在第几场、
铺垫多长、结尾留什么扣子把观众拽到下一集。这一层直接决定短剧完播率，
却是纯生成模型最容易失控的地方（爽点均匀平铺、前 15 秒无钩子）。

本模块把「集结构」变成可编排、可校验的显式对象：
  1. ``build_beat_sheet``   —— 按集长与爽点密度预算排出节拍表（beat sheet）
  2. ``design_hook_open``   —— 选开场钩子类型并给出 3 秒/15 秒双层钩子
  3. ``place_payoffs``      —— 把爽点/甜点/悬念按密度预算排进场次
  4. ``narrative_qa``       —— 校验节拍表：钩子缺失、爽点缺失/过密、拖沓、结尾无扣

节拍表（beat sheet）结构::

    {
      "episode_no": 3,
      "target_duration_s": 120,
      "hook_budget_s": 15,
      "beats": [
        {"index": 0, "role": "hook", "type": "conflict_open",
         "start_s": 0, "end_s": 8, "scene_id": "s1",
         "note": "开场直接给冲突画面"},
        ...
      ],
      "payoffs": [{"kind": "爽点", "at_s": 62, "beat_index": 4}],
    }
"""
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 集结构角色（一个 beat 的叙事职能）
# ---------------------------------------------------------------------------
BEAT_ROLES = [
    "hook",       # 开场钩子：3 秒内抓人
    "setup",      # 铺垫：交代处境/关系
    "escalate",   # 升级：冲突加码
    "payoff",     # 爽点：期待兑现
    "sweet",      # 甜点：关系回暖
    "twist",      # 反转
    "cliff",      # 悬念扣：拽向下一集
]

# 角色时长占比建议（同一集内）
_ROLE_RATIO = {
    "hook": (0.05, 0.12),
    "setup": (0.10, 0.22),
    "escalate": (0.15, 0.30),
    "payoff": (0.10, 0.25),
    "sweet": (0.05, 0.15),
    "twist": (0.05, 0.15),
    "cliff": (0.03, 0.10),
}

# 短剧爽点密度基线（每集爽点数 / 每集甜点数）
# 白皇创作铁律：每章/每集 ≥3 爽点 + 1 甜点
PAYOFF_DENSITY = {"min_payoff": 3, "min_sweet": 1}
# 前 15 秒必须出现钩子（完播率第一道闸）
HOOK_DEADLINE_S = 15
# 相邻爽点最小间隔（低于此值观众会认为是同一段戏反复吊胃口）
MIN_PAYOFF_GAP_S = 12
# 单集爽点上限（超过则观众钝化）
MAX_PAYOFF_PER_EPISODE = 8


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _round(x: float, n: int = 1) -> float:
    return round(x + 0.0, n)


# ---------------------------------------------------------------------------
# 1) 节拍表编排
# ---------------------------------------------------------------------------
def build_beat_sheet(episode_no: int,
                     target_duration_s: int,
                     scenes: List[Dict[str, Any]],
                     n_payoff: int = 3,
                     n_sweet: int = 1,
                     has_twist: bool = True,
                     ) -> Dict[str, Any]:
    """按集长与爽点预算排出节拍表。

    :param episode_no: 集号（从 1 开始）
    :param target_duration_s: 目标集长（秒）
    :param scenes: 本集可用场次列表，每项至少含 ``scene_id``；可选 ``role``
        （指定该场在结构中的职能）、``duration_s``
    :param n_payoff: 爽点数量（默认按铁律取 3）
    :param n_sweet: 甜点数量（默认 1）
    :param has_twist: 是否安排反转
    :return: beat sheet dict
    """
    scenes = list(scenes or [])
    if not scenes:
        return {
            "episode_no": episode_no,
            "target_duration_s": target_duration_s,
            "beats": [],
            "payoffs": [],
            "note": "无场次，无法排节拍",
        }

    n_payoff = max(0, int(n_payoff))
    n_sweet = max(0, int(n_sweet))
    has_twist = bool(has_twist)

    # 需要的节拍数量：hook + setup + escalate* + payoff* + sweet* + twist? + cliff
    n_setup = 1
    n_escalate = max(1, min(len(scenes) - 2, 2))
    n_beat = 1 + n_setup + n_escalate + n_payoff + n_sweet + (1 if has_twist else 0) + 1
    # 场次不够时，节拍可多于场次（一场多拍），但不允许少于场次
    n_beat = max(n_beat, min(len(scenes), n_beat))

    # 组装 beat 角色序列
    roles: List[str] = ["hook", "setup"]
    roles += ["escalate"] * n_escalate
    roles += ["payoff"] * n_payoff
    roles += ["sweet"] * n_sweet
    if has_twist:
        roles.insert(max(2, len(roles) - 2), "twist")
    roles.append("cliff")

    # 分配时长：按角色建议占比归一化
    weights = []
    for r in roles:
        lo, hi = _ROLE_RATIO.get(r, (0.08, 0.2))
        weights.append((lo + hi) / 2.0)
    total_w = sum(weights) or 1.0
    durations = [int(round(target_duration_s * w / total_w)) for w in weights]
    # 修正取整误差
    diff = target_duration_s - sum(durations)
    durations[-1] += diff
    durations = [max(1, d) for d in durations]

    beats: List[Dict[str, Any]] = []
    t = 0
    for i, (role, dur) in enumerate(zip(roles, durations)):
        sc = scenes[i % len(scenes)]
        beats.append({
            "index": i,
            "role": role,
            "type": sc.get("role", role),
            "start_s": t,
            "end_s": t + dur,
            "duration_s": dur,
            "scene_id": sc.get("scene_id", "s%d" % (i + 1)),
            "note": sc.get("note", ""),
        })
        t += dur

    # 爽点/甜点落点（从对应 beat 里取时刻）
    payoffs: List[Dict[str, Any]] = []
    for b in beats:
        if b["role"] == "payoff":
            payoffs.append({"kind": "爽点", "at_s": b["start_s"], "beat_index": b["index"],
                            "scene_id": b["scene_id"]})
        elif b["role"] == "sweet":
            payoffs.append({"kind": "甜点", "at_s": b["start_s"], "beat_index": b["index"],
                            "scene_id": b["scene_id"]})
        elif b["role"] == "twist":
            payoffs.append({"kind": "反转", "at_s": b["start_s"], "beat_index": b["index"],
                            "scene_id": b["scene_id"]})

    return {
        "episode_no": episode_no,
        "target_duration_s": target_duration_s,
        "hook_budget_s": min(HOOK_DEADLINE_S, int(target_duration_s * 0.12)),
        "beats": beats,
        "payoffs": payoffs,
        "note": "按角色占比归一化分配时长",
    }


# ---------------------------------------------------------------------------
# 2) 钩子设计
# ---------------------------------------------------------------------------
# 开场钩子类型 -> (说明, 适配场景标签)
HOOK_TYPES = {
    "conflict_open": ("直接给冲突画面，双方对峙", ["revenge", "face_slap", "romance_conflict"]),
    "suspense_line": ("一句悬念台词 + 异常画面", ["mystery", "suspense"]),
    "reverse_open": ("倒叙：先给结果，再回到起因", ["revenge", "rebirth", "time_travel"]),
    "public_humiliation": ("当众受辱，激发报复欲", ["face_slap", "revenge", "rural"]),
    "mystery_reveal": ("抛出未解之谜", ["mystery", "suspense"]),
    "betrayal_tease": ("背叛瞬间，一闪而过", ["romance", "revenge"]),
    "power_show": ("主角展露实力，身份反差", ["ceo", "rebirth", "urban"]),
    "dark_horse": ("平凡主角即将逆袭的暗示", ["urban", "revenge", "rural"]),
    "tease_romance": ("暧昧片段，制造 CP 期待", ["romance", "sweet"]),
    "danger_warning": ("危险预警，性命攸关", ["suspense", "mystery"]),
    "money_shock": ("巨额数字/账单，冲击", ["urban", "ceo", "revenge"]),
    "identity_tease": ("身份即将暴露的临界点", ["face_slap", "revenge"]),
    "weird_normal": ("反常日常，制造违和感", ["suspense", "comedy"]),
    "countdown": ("倒计时/限时危机", ["suspense", "revenge"]),
    "nostalgic_hook": ("旧物/回忆切入，情感共鸣", ["sweet", "nostalgia"]),
    "cold_open_question": ("开场抛问题，悬念式提问", ["mystery", "revenge"]),
}


def design_hook_open(sheet: Dict[str, Any],
                     tags: Optional[List[str]] = None,
                     hook_type: Optional[str] = None,
                     ) -> Dict[str, Any]:
    """为某集设计开场钩子（3 秒层 + 15 秒层）。

    :param sheet: ``build_beat_sheet`` 的产物
    :param tags: 本集场景标签（如 ``["revenge", "face_slap"]``），用于挑适配钩子
    :param hook_type: 指定钩子类型；不给则按标签自动挑
    :return: 钩子设计 dict
    """
    tags = [str(t).lower() for t in (tags or [])]
    beats = (sheet or {}).get("beats") or []
    hook_beat = next((b for b in beats if b.get("role") == "hook"), None)
    hook_window_s = int((sheet or {}).get("hook_budget_s") or HOOK_DEADLINE_S)

    if hook_type and hook_type in HOOK_TYPES:
        chosen = hook_type
    else:
        chosen = None
        for hk, (_desc, suited) in HOOK_TYPES.items():
            if any(t in suited for t in tags):
                chosen = hk
                break
        if chosen is None:
            chosen = "conflict_open"

    desc, suited = HOOK_TYPES[chosen]
    return {
        "hook_type": chosen,
        "description": desc,
        "suited_tags": suited,
        "hook_beat_index": (hook_beat or {}).get("index", 0),
        "window_s": hook_window_s,
        "layer_3s": "0-3s：不给背景，只给「异常/冲突/悬念」的一个画面或一句台词",
        "layer_15s": "3-15s：补足「谁想要什么、挡路的是谁」，让观众站队",
        "scene_id": (hook_beat or {}).get("scene_id"),
    }


# ---------------------------------------------------------------------------
# 3) 爽点排布
# ---------------------------------------------------------------------------
def place_payoffs(sheet: Dict[str, Any],
                  payoff_points: List[Dict[str, Any]],
                  ) -> Dict[str, Any]:
    """把真实爽点/甜点内容挂到节拍表上。

    :param sheet: beat sheet
    :param payoff_points: 爽点条目列表，每项含 ``kind``（爽点/甜点/反转）与
        可选 ``content`` / ``duration_s`` / ``beat_index``（指定挂载节拍）
    :return: 附带 ``placed`` 的 sheet
    """
    sheet = dict(sheet or {})
    beats = sheet.get("beats") or []
    payoff_beats = [b for b in beats if b.get("role") == "payoff"]
    sweet_beats = [b for b in beats if b.get("role") == "sweet"]
    twist_beats = [b for b in beats if b.get("role") == "twist"]

    pools = {"爽点": payoff_beats, "甜点": sweet_beats, "反转": twist_beats}
    used = {k: 0 for k in pools}
    placed: List[Dict[str, Any]] = []
    unplaced: List[Dict[str, Any]] = []

    for i, p in enumerate(payoff_points or []):
        p = dict(p or {})
        kind = p.get("kind", "爽点")
        pool = pools.get(kind, payoff_beats)
        idx = p.get("beat_index")
        if idx is None:
            if used.get(kind, 0) < len(pool):
                idx = pool[used[kind]]["index"]
                used[kind] += 1
            else:
                unplaced.append(p)
                continue
        target = next((b for b in beats if b.get("index") == idx), None)
        if target is None:
            unplaced.append(p)
            continue
        dur = int(p.get("duration_s") or 0)
        placed.append({
            "kind": kind,
            "content": p.get("content", ""),
            "beat_index": idx,
            "at_s": target.get("start_s"),
            "duration_s": dur or int(target.get("duration_s", 0)),
            "scene_id": target.get("scene_id"),
        })

    sheet["payoffs"] = placed
    sheet["unplaced"] = unplaced
    return sheet


# ---------------------------------------------------------------------------
# 4) 叙事质检
# ---------------------------------------------------------------------------
def narrative_qa(sheet: Dict[str, Any],
                 n_payoff_expected: Optional[int] = None,
                 n_sweet_expected: Optional[int] = None,
                 ) -> Dict[str, Any]:
    """校验节拍表：钩子 / 爽点密度 / 拖沓 / 结尾扣子。

    返回 ``{"passed", "score", "issues", "stats"}``；issues 内每项含
    ``level``（block/warn）、``code``、``message``。
    """
    sheet = sheet or {}
    beats = sheet.get("beats") or []
    placed = sheet.get("payoffs") or []
    issues: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {}

    if not beats:
        return {
            "passed": False,
            "score": 0.0,
            "issues": [{"level": "block", "code": "NO_BEATS", "message": "节拍表为空"}],
            "stats": {},
        }

    n_pay = sum(1 for p in placed if p.get("kind") == "爽点")
    n_swt = sum(1 for p in placed if p.get("kind") == "甜点")
    n_tw = sum(1 for p in placed if p.get("kind") == "反转")
    hook_beats = [b for b in beats if b.get("role") == "hook"]
    cliff_beats = [b for b in beats if b.get("role") == "cliff"]
    total_s = int(sheet.get("target_duration_s") or 0)
    if not total_s:
        total_s = int(beats[-1].get("end_s") or 0)

    stats.update({
        "n_beats": len(beats),
        "n_payoff": n_pay,
        "n_sweet": n_swt,
        "n_twist": n_tw,
        "total_duration_s": total_s,
    })

    # 4.1 开场钩子
    if not hook_beats:
        issues.append({"level": "block", "code": "NO_HOOK",
                       "message": "缺少开场钩子，前 15 秒无抓点完播率必崩"})
    else:
        h = hook_beats[0]
        if h.get("end_s", 0) > HOOK_DEADLINE_S:
            issues.append({"level": "warn", "code": "HOOK_TOO_LATE",
                           "message": "开场钩子结束于 %ds，超过 %ds 阈值"
                                      % (h.get("end_s"), HOOK_DEADLINE_S)})
        stats["hook_end_s"] = h.get("end_s")

    # 4.2 爽点/甜点数量
    exp_pay = PAYOFF_DENSITY["min_payoff"] if n_payoff_expected is None else int(n_payoff_expected)
    exp_swt = PAYOFF_DENSITY["min_sweet"] if n_sweet_expected is None else int(n_sweet_expected)
    if n_pay < exp_pay:
        issues.append({"level": "block", "code": "PAYOFF_TOO_FEW",
                       "message": "爽点 %d 个，少于下限 %d 个" % (n_pay, exp_pay)})
    if n_swt < exp_swt:
        issues.append({"level": "warn", "code": "SWEET_TOO_FEW",
                       "message": "甜点 %d 个，少于建议 %d 个" % (n_swt, exp_swt)})
    if n_pay > MAX_PAYOFF_PER_EPISODE:
        issues.append({"level": "warn", "code": "PAYOFF_OVERLOAD",
                       "message": "爽点 %d 个超过 %d 个上限，观众会钝化"
                                  % (n_pay, MAX_PAYOFF_PER_EPISODE)})

    # 4.3 爽点间距
    pay_times = sorted(int(p.get("at_s") or 0) for p in placed if p.get("kind") == "爽点")
    for i in range(1, len(pay_times)):
        gap = pay_times[i] - pay_times[i - 1]
        if gap < MIN_PAYOFF_GAP_S:
            issues.append({"level": "warn", "code": "PAYOFF_TOO_CLOSE",
                           "message": "第 %d 与第 %d 个爽点间隔 %ds，低于 %ds，观众会觉得反复吊胃口"
                                      % (i, i + 1, gap, MIN_PAYOFF_GAP_S)})
    if len(pay_times) >= 2:
        stats["payoff_gap_min_s"] = min(pay_times[i] - pay_times[i - 1]
                                        for i in range(1, len(pay_times)))

    # 4.4 拖沓：setup 占比过高
    setup_s = sum(int(b.get("duration_s") or 0) for b in beats if b.get("role") == "setup")
    if total_s and setup_s / float(total_s) > 0.35:
        issues.append({"level": "warn", "code": "SETUP_TOO_LONG",
                       "message": "铺垫占 %.0f%%（%ds/%ds），超过 35%% 建议上限"
                                  % (setup_s * 100.0 / total_s, setup_s, total_s)})
    stats["setup_ratio"] = _round(setup_s / float(total_s), 3) if total_s else 0.0

    # 4.5 结尾扣子
    if not cliff_beats:
        issues.append({"level": "warn", "code": "NO_CLIFF",
                       "message": "结尾无悬念扣，完播后难以转下一集"})

    # 4.6 时长越界
    if total_s and total_s < 30:
        issues.append({"level": "warn", "code": "TOO_SHORT",
                       "message": "集长仅 %ds，短于 30s 难以承载爽点结构" % total_s})

    blocks = [i for i in issues if i["level"] == "block"]
    warns = [i for i in issues if i["level"] == "warn"]
    score = 100.0 - 25.0 * len(blocks) - 8.0 * len(warns)
    score = _clamp(score, 0.0, 100.0)
    return {
        "passed": (not blocks),
        "score": score,
        "issues": issues,
        "stats": stats,
        "n_block": len(blocks),
        "n_warn": len(warns),
    }


def episode_architect(episode_no: int,
                      target_duration_s: int,
                      scenes: List[Dict[str, Any]],
                      tags: Optional[List[str]] = None,
                      payoff_points: Optional[List[Dict[str, Any]]] = None,
                      n_payoff: int = 3,
                      n_sweet: int = 1,
                      has_twist: bool = True,
                      ) -> Dict[str, Any]:
    """一站式：排节拍表 → 配钩子 → 挂爽点 → 质检。

    返回 ``{"sheet", "hook", "qa", "passed"}``。
    """
    sheet = build_beat_sheet(episode_no, target_duration_s, scenes,
                             n_payoff=n_payoff, n_sweet=n_sweet, has_twist=has_twist)
    hook = design_hook_open(sheet, tags=tags)
    if payoff_points:
        sheet = place_payoffs(sheet, payoff_points)
    qa = narrative_qa(sheet)
    return {
        "sheet": sheet,
        "hook": hook,
        "qa": qa,
        "passed": qa.get("passed", False),
    }
