# -*- coding: utf-8 -*-
"""hook_engine：开场钩子（完播率第一道闸）的生成、评估与 A/B 备选。

与 ``narrative_architect.design_hook_open`` 的分工
---------------------------------------------------
``design_hook_open`` 负责**结构层面**：把钩子挂到节拍表的哪个位置、给多少秒。
本模块负责**内容层面**：钩子具体说什么话、怎么画面开场、够不够狠、
以及给出可 A/B 测试的备选方案。

短剧开场钩子的判定标准（本模块量化的部分）
--------------------------------------------
  1. **冲突前置**：0-3s 内必须出现「某人想要什么 / 什么在挡路」
  2. **信息缺口**：观众必须产生一个待解的问题（否则划走）
  3. **情绪落差**：平静开场 + 强刺激画面的反差
  4. **可兑现**：钩子承诺的爽点必须在集内或近期集兑现，不能骗

本模块提供：
  1. ``score_hook``      —— 给钩子打分（5 个维度，0-100）
  2. ``write_hook_line`` —— 生成钩子台词/画面描述（模板 + 变量，不调 LLM）
  3. ``ab_variants``     —— 生成 A/B/C 备选钩子
  4. ``hook_gate``       —— 发布前闸门：低于阈值直接拦
"""
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 钩子类型定义
# ---------------------------------------------------------------------------
HOOK_CATALOG: Dict[str, Dict[str, Any]] = {
    "conflict_open": {
        "label": "冲突直给",
        "desc": "第一帧就是对峙/冲突，不给任何铺垫",
        "emotion": "愤怒/紧张",
        "promise": "冲突会被正面解决",
        "beat": 88,
    },
    "suspense_line": {
        "label": "悬念台词",
        "desc": "一句反常台词配异常画面",
        "emotion": "好奇/不安",
        "promise": "这句台词的含义会在剧中揭晓",
        "beat": 85,
    },
    "reverse_open": {
        "label": "倒叙",
        "desc": "先给结果（打脸/身死），再倒回起因",
        "emotion": "震撼/解气",
        "promise": "讲述结果是怎么来的",
        "beat": 90,
    },
    "public_humiliation": {
        "label": "当众受辱",
        "desc": "主角被当众羞辱，激发报复欲",
        "emotion": "憋屈/愤怒",
        "promise": "主角会找回场子",
        "beat": 87,
    },
    "mystery_reveal": {
        "label": "抛出谜团",
        "desc": "出现无法解释的异常（重生的证据/不该存在的物件）",
        "emotion": "震惊/好奇",
        "promise": "谜团会被解开",
        "beat": 83,
    },
    "betrayal_tease": {
        "label": "背叛一闪",
        "desc": "背叛瞬间一闪而过，不解释",
        "emotion": "愤怒/心疼",
        "promise": "背叛者会付出代价",
        "beat": 84,
    },
    "power_show": {
        "label": "实力碾压",
        "desc": "主角展露与身份不符的能力或身份",
        "emotion": "爽/惊讶",
        "promise": "这份实力会用于反击",
        "beat": 86,
    },
    "dark_horse": {
        "label": "黑马暗示",
        "desc": "平凡主角被暗示将逆袭",
        "emotion": "期待",
        "promise": "逆袭会发生",
        "beat": 78,
    },
    "tease_romance": {
        "label": "暧昧撩拨",
        "desc": "高甜互动片段，制造 CP 期待",
        "emotion": "心动/甜",
        "promise": "关系会有进展",
        "beat": 76,
    },
    "danger_warning": {
        "label": "危险预警",
        "desc": "性命攸关的危机瞬间",
        "emotion": "紧张/揪心",
        "promise": "危机会被化解或升级",
        "beat": 82,
    },
    "money_shock": {
        "label": "数字冲击",
        "desc": "巨额账单/赔偿/彩礼数字特写",
        "emotion": "惊讶/不服",
        "promise": "这笔钱会改变局面",
        "beat": 74,
    },
    "identity_tease": {
        "label": "身份临界",
        "desc": "身份即将暴露的瞬间",
        "emotion": "紧张/期待",
        "promise": "身份会曝光",
        "beat": 81,
    },
    "weird_normal": {
        "label": "反常日常",
        "desc": "一切正常但有一处不对劲",
        "emotion": "不安/好奇",
        "promise": "反常点会被解释",
        "beat": 77,
    },
    "countdown": {
        "label": "限时倒计时",
        "desc": "倒计时/限时任务制造紧迫",
        "emotion": "紧迫",
        "promise": "倒计时结束前会有结果",
        "beat": 80,
    },
    "nostalgic_hook": {
        "label": "旧物回忆",
        "desc": "旧物/旧照切入，触发情感共鸣",
        "emotion": "怀念/酸涩",
        "promise": "回忆会牵出往事真相",
        "beat": 70,
    },
    "cold_open_question": {
        "label": "冷开场提问",
        "desc": "开场即抛一个问题，答案在后面",
        "emotion": "好奇",
        "promise": "问题会被回答",
        "beat": 75,
    },
}

# 钩子类型 -> 适配的场景标签
SUITED_TAGS: Dict[str, List[str]] = {
    "conflict_open": ["revenge", "face_slap", "urban", "rural"],
    "suspense_line": ["mystery", "suspense"],
    "reverse_open": ["revenge", "rebirth", "time_travel", "face_slap"],
    "public_humiliation": ["face_slap", "revenge", "rural"],
    "mystery_reveal": ["mystery", "suspense", "rebirth"],
    "betrayal_tease": ["romance", "revenge"],
    "power_show": ["ceo", "rebirth", "urban", "rural"],
    "dark_horse": ["urban", "revenge", "rural", "comedy"],
    "tease_romance": ["romance", "sweet"],
    "danger_warning": ["suspense", "mystery"],
    "money_shock": ["urban", "ceo", "revenge", "rural"],
    "identity_tease": ["face_slap", "revenge", "mystery"],
    "weird_normal": ["suspense", "comedy"],
    "countdown": ["suspense", "revenge", "urban"],
    "nostalgic_hook": ["sweet", "nostalgia", "rural"],
    "cold_open_question": ["mystery", "revenge"],
}

# 评分权重
_SCORE_WEIGHTS = {
    "conflict": 0.30,   # 冲突前置
    "gap": 0.25,       # 信息缺口
    "emotion": 0.20,   # 情绪落差
    "promise": 0.15,   # 可兑现
    "clarity": 0.10,   # 表达清晰
}

# 发布闸门阈值
GATE_THRESHOLD = 70.0


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# 1) 钩子打分
# ---------------------------------------------------------------------------
def score_hook(hook: Dict[str, Any]) -> Dict[str, Any]:
    """给一个钩子打分。

    :param hook: 钩子描述字典，可用键：
        ``hook_type``（见 HOOK_CATALOG）、``conflict``（bool/0-1，是否有正面冲突）、
        ``question``（观众心里的疑问，可为 str 或 bool）、
        ``emotion_delta``（情绪落差强度 0-1）、
        ``promise_kept``（承诺是否会兑现，bool）、
        ``line``（钩子台词/描述文本）
    :return: ``{"score","dims","level","issues","hook_type"}``
    """
    hook = hook or {}
    htype = hook.get("hook_type") or "conflict_open"
    meta = HOOK_CATALOG.get(htype, {})

    dims: Dict[str, float] = {}

    # 冲突前置
    c = hook.get("conflict")
    if c is None:
        c = 1.0 if htype in ("conflict_open", "public_humiliation", "power_show",
                             "betrayal_tease", "danger_warning") else 0.5
    dims["conflict"] = _clamp(float(c) * 100.0)

    # 信息缺口
    g = hook.get("question")
    if g is None:
        g = 0.6 if htype in ("suspense_line", "mystery_reveal", "identity_tease",
                             "weird_normal", "cold_open_question", "countdown") else 0.4
    elif isinstance(g, str):
        g = 1.0 if len(g.strip()) >= 4 else 0.4
    dims["gap"] = _clamp(float(g) * 100.0)

    # 情绪落差
    e = hook.get("emotion_delta")
    if e is None:
        e = 0.7 if meta.get("emotion") in ("愤怒/紧张", "震撼/解气", "憋屈/愤怒",
                                           "紧张/揪心", "紧迫") else 0.55
    dims["emotion"] = _clamp(float(e) * 100.0)

    # 可兑现
    p = hook.get("promise_kept")
    if p is None:
        p = 1.0
    dims["promise"] = _clamp(float(p) * 100.0)

    # 表达清晰
    line = (hook.get("line") or "").strip()
    if line:
        dims["clarity"] = _clamp(100.0 if 4 <= len(line) <= 40 else 70.0)
    else:
        dims["clarity"] = 60.0

    score = sum(dims[k] * _SCORE_WEIGHTS[k] for k in _SCORE_WEIGHTS)

    # 问题清单
    issues: List[str] = []
    if dims["conflict"] < 60:
        issues.append("冲突前置不足：0-3s 内看不到「谁要什么、什么挡路」")
    if dims["gap"] < 50:
        issues.append("信息缺口不足：观众没有产生待解疑问，容易划走")
    if dims["emotion"] < 55:
        issues.append("情绪落差不足：开场平淡，缺少刺激点")
    if dims["promise"] < 80:
        issues.append("承诺可能无法兑现：钩子许诺的爽点要在集内或近期集落地")
    if dims["clarity"] < 70:
        issues.append("钩子表达不清晰：台词过长或缺失")

    level = "strong" if score >= 80 else ("ok" if score >= GATE_THRESHOLD else "weak")
    return {
        "hook_type": htype,
        "label": meta.get("label", htype),
        "score": round(score, 1),
        "level": level,
        "dims": {k: round(v, 1) for k, v in dims.items()},
        "issues": issues,
        "passed": score >= GATE_THRESHOLD and not any(
            dims[k] < 50 for k in ("conflict", "gap")),
    }


# ---------------------------------------------------------------------------
# 2) 钩子内容生成（模板化，不调 LLM）
# ---------------------------------------------------------------------------
_LINE_TEMPLATES = {
    "conflict_open": [
        "把「{blocking}」按在桌上，{hero}只说了一句：「这事我管定了。」",
        "{hero}刚要进门，就听见{blocking}。他停住，回头。",
        "「{blocking}要的东西，{hero}已经拿走了。」{hero}头也没回。",
    ],
    "suspense_line": [
        "{hero}看着{object}，说了句所有人都听不懂的话：「{line}」",
        "「{line}」——{hero}说完这句，全场安静了。",
        "{hero}只说了四个字：「{line}」。整栋楼的人，都停下了手里的事。",
    ],
    "reverse_open": [
        "这是{ending}的最后一秒。没人知道{hero}是怎么做到的。",
        "{hero}倒在地上的时候，嘴角是笑的。事情要从三分钟前说起。",
        "{ending}之前，{hero}谁都不认识。可三分钟后，全场都记住了这个名字。",
    ],
    "public_humiliation": [
        "「你算什么？」{blocking}当着所有人的面，把东西摔在{hero}脚下。",
        "所有人都在笑{hero}。只有一个人没笑。",
        "{blocking}把{object}砸在{hero}身上：「滚。」{hero}没动。",
    ],
    "mystery_reveal": [
        "{hero}翻开{object}，愣住了——上面的日期，是明天。",
        "{object}还在{hero}手里，可屋里明明只有他一个人。",
        "{object}上刻着{hero}的名字。可这间屋子，三年没人来过。",
    ],
    "betrayal_tease": [
        "画面只闪了半秒：{other}手里的东西，落在了别人身上。",
        "{other}的道歉，{hero}一个字都没听进去。",
        "{other}收回手，指尖还沾着血。他以为没人看见。",
    ],
    "power_show": [
        "所有人都在等{hero}道歉。他抬了下头，事情就不一样了。",
        "{hero}把手里的{object}放下，整间屋子安静了。",
        "{blocking}带了十个人来。{hero}只抬了一下眼。",
    ],
    "dark_horse": [
        "没有人看好{hero}。包括他自己。",
        "{hero}看起来什么都不是。这正是问题所在。",
        "所有人都说{hero}是来陪衬的。他们还不知道谁才是主角。",
    ],
    "tease_romance": [
        "{other}伸手替{hero}理了理衣领，然后退开，什么都没说。",
        "两个人的距离只有一拳，谁都没动。",
        "{other}把伞往{hero}那边偏了三寸，自己半边肩膀全湿了。",
    ],
    "danger_warning": [
        "「别回头。」{hero}的声音在发抖。但已经晚了。",
        "{hero}看见{object}的那一刻，明白自己跑不掉了。",
        "身后传来刹车声。{hero}没回头——他已经知道是谁。",
    ],
    "money_shock": [
        "屏幕上那个数字，{hero}数了三遍。",
        "{blocking}甩过来一张单子：{object}。数字大到没人出声。",
        "{blocking}报的价是{object}。{hero}笑了一下，掏出了卡。",
    ],
    "identity_tease": [
        "有人喊了一声「{line}」。{hero}的筷子停了。",
        "{hero}以为没人知道。可{name}已经叫出了他的{line}。",
        "{name}叫出了{hero}的名字，和另一个名字。{hero}手里的杯子碎了。",
    ],
    "weird_normal": [
        "所有人都说今天和昨天一样。只有{hero}觉得不对。",
        "第 {n} 次，{hero}又看见了那个{object}。",
        "所有人都说今天和昨天一样。只有{object}的位置，变了。",
    ],
    "countdown": [
        "「还剩 {n} 分钟。」{hero}把手机翻过去，站了起来。",
        "倒计时从 {n} 开始。{hero}只有这一次机会。",
        "「{n} 分钟。」{hero}已经在路上了。",
    ],
    "nostalgic_hook": [
        "{hero}翻出那张旧照片。上面的人，笑着。",
        "很多年后{hero}才知道，{object}那天为什么一直响。",
        "{hero}放起那首歌。屋里的灯，忽然又亮了。",
    ],
    "cold_open_question": [
        "{hero}问了一句：「{line}？」屋里没有人回答。",
        "如果{hero}那天没有回头，一切都会不一样吗？",
        "{hero}忽然问：「{line}？」没人知道他为什么问这一句。",
    ],
}

_DEFAULT_VARS = {
    "hero": "他",
    "other": "她",
    "blocking": "对方",
    "object": "那份文件",
    "line": "这件事不对",
    "n": "3",
    "name": "那个人",
    "ending": "翻盘",
}


def write_hook_line(hook_type: str,
                    variables: Optional[Dict[str, str]] = None,
                    variant: int = 0) -> Dict[str, Any]:
    """生成钩子台词 + 画面描述。

    :param hook_type: HOOK_CATALOG 里的类型
    :param variables: 变量覆盖（如 ``{"hero": "林晚", "blocking": "陆家"}``）
    :param variant: 选第几条模板
    :return: ``{"hook_type","line","shot","beat"}``
    """
    htype = hook_type if hook_type in HOOK_CATALOG else "conflict_open"
    tpls = _LINE_TEMPLATES.get(htype) or _LINE_TEMPLATES["conflict_open"]
    idx = int(variant) % len(tpls)
    tpl = tpls[idx]
    vars_ = dict(_DEFAULT_VARS)
    vars_.update({k: str(v) for k, v in (variables or {}).items()})
    try:
        line = tpl.format(**vars_)
    except KeyError:
        line = tpl
    meta = HOOK_CATALOG.get(htype, {})
    return {
        "hook_type": htype,
        "label": meta.get("label", htype),
        "line": line,
        "shot": "0-3s 画面：不给全景，直接给「%s」的情绪特写或反常道具" % meta.get("emotion", "强情绪"),
        "beat": meta.get("beat", 0),
        "promise": meta.get("promise", ""),
    }


# ---------------------------------------------------------------------------
# 3) A/B 备选
# ---------------------------------------------------------------------------
def ab_variants(hook_type: str,
                variables: Optional[Dict[str, str]] = None,
                n: int = 3) -> List[Dict[str, Any]]:
    """生成 A/B/C 备选钩子（同一类型的不同台词版本），供实跑数据选优。"""
    htype = hook_type if hook_type in HOOK_CATALOG else "conflict_open"
    tpls = _LINE_TEMPLATES.get(htype) or _LINE_TEMPLATES["conflict_open"]
    out: List[Dict[str, Any]] = []
    for i in range(max(1, min(int(n), len(tpls)))):
        v = write_hook_line(htype, variables, variant=i)
        v["variant"] = chr(ord("A") + i)
        sc = score_hook({"hook_type": htype, "line": v.get("line")})
        v["score"] = sc["score"]
        v["level"] = sc["level"]
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# 4) 发布闸门
# ---------------------------------------------------------------------------
def hook_gate(hooks: List[Dict[str, Any]],
              threshold: float = GATE_THRESHOLD) -> Dict[str, Any]:
    """发布前闸门：所有钩子都要过线才放行。

    :param hooks: 钩子列表（每项可含 ``episode_no`` 与 ``hook_type``/``line`` 等）
    :param threshold: 通过阈值（默认 70）
    :return: ``{"passed","threshold","results","blocked"}``
    """
    res: List[Dict[str, Any]] = []
    blocked: List[Any] = []
    for i, h in enumerate(hooks or []):
        sc = score_hook(h)
        entry = {
            "episode_no": (h or {}).get("episode_no", i + 1),
            "hook_type": sc["hook_type"],
            "score": sc["score"],
            "level": sc["level"],
            "passed": sc["passed"] and sc["score"] >= threshold,
            "issues": sc["issues"],
        }
        res.append(entry)
        if not entry["passed"]:
            blocked.append(entry["episode_no"])
    return {
        "passed": not blocked,
        "threshold": threshold,
        "results": res,
        "blocked": blocked,
        "n_blocked": len(blocked),
    }


def recommend_hook_type(tags: List[str],
                        prefer: Optional[List[str]] = None) -> List[str]:
    """按场景标签给钩子类型推荐排序（分高且适配的排前面）。"""
    tags_l = [str(t).lower() for t in (tags or [])]
    prefer_l = [str(t).lower() for t in (prefer or [])]
    scored = []
    for hk, meta in HOOK_CATALOG.items():
        suited = SUITED_TAGS.get(hk, [])
        fit = 0
        for t in tags_l:
            if t in suited:
                fit += 2
        boost = 0
        for t in prefer_l:
            if t in suited:
                boost += 3
        scored.append((-fit - boost, -meta.get("beat", 0), hk))
    scored.sort()
    return [s[2] for s in scored]
