# -*- coding: utf-8 -*-
"""8 环节全链路管线执行器：按 dataflow 拓扑排序逐环节执行。

把 workflow_gen.build_dataflow 产出的 8 环节依赖图落成可执行管线：
  剧本输入 → script_struct → character_image → storyboard_prompt → video_shot
            → fx_enhance → post_assemble → bgm_audio → package_publish
每个环节执行器是一个 callable(executor_map[id]), 接收 upstream 产物 dict, 返回本环节产物。
环节产物自动喂给下游（按 depends_on_eff 聚合）。拓扑排序保证依赖先跑。

市场短板补口：现有 orchestrator 只做"镜头级"失败路由；本模块补"8 环节 dataflow 拓扑级"
编排，把 6 维全赢从指标领先落到可执行管线。
"""
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


class TopologyError(Exception):
    """数据流存在环或悬空依赖。"""


def topo_order(dataflow: List[Dict[str, Any]]) -> List[str]:
    """对 8 环节数据流做拓扑排序（Kahn），返回环节 id 执行顺序。

    环或悬空依赖（depends_on 指向不存在的环节）→ 抛 TopologyError。
    """
    ids = [f["id"] for f in dataflow]
    id_set = set(ids)
    # 入度 = 有效上游依赖数（仅统计 id_set 内的依赖）
    indeg = {i: 0 for i in ids}
    dependents: Dict[str, List[str]] = {i: [] for i in ids}
    for f in dataflow:
        for d in f.get("depends_on_eff", []):
            if d in id_set:
                indeg[f["id"]] += 1
                dependents[d].append(f["id"])
    queue = [i for i in ids if indeg[i] == 0]
    order: List[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in dependents[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(ids):
        cyc = [i for i in ids if i not in set(order)]
        raise TopologyError(f"数据流存在环或悬空依赖: {cyc}")
    return order


def run_pipeline_8stage(workflow: Dict[str, Any],
                        executors: Dict[str, Callable],
                        upstream_inputs: Optional[Dict[str, Any]] = None,
                        resume_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """按 8 环节 dataflow 拓扑序执行。

    workflow: workflow_gen.generate_workflow 返回值（含 dataflow）
    executors: 环节 id -> 执行器。执行器签名:
        executor(upstream: Dict[str, Any]) -> Dict[str, Any]
        入参 upstream = {依赖环节 id: 该环节产物}
    upstream_inputs: 环节 id -> 输入（喂给环节 1 的剧本等）
    resume_ids: 已成功、跳过重跑的环节 id（断点）
    返回:
      {
        "order": [...], "completed": [id], "skipped": [id],
        "artifacts": {环节 id: 产物}, "failed": {环节 id: 错误},
        "ok": bool
      }
    """
    dataflow = workflow.get("dataflow", [])
    order = topo_order(dataflow)
    df_map = {f["id"]: f for f in dataflow}
    resume = set(resume_ids or [])
    artifacts: Dict[str, Any] = {}
    failed: Dict[str, str] = {}
    completed: List[str] = []
    upstream_inputs = upstream_inputs or {}

    for nid in order:
        if nid in resume:
            completed.append(nid)
            artifacts[nid] = {"_resumed": True}
            continue
        spec = df_map[nid]
        # 聚合本环节上游产物
        upstream: Dict[str, Any] = {}
        for d in spec.get("depends_on_eff", []):
            if d in artifacts:
                upstream[d] = artifacts[d]
        # 环节 1 用外部输入（剧本）
        if nid not in upstream or upstream.get(nid) is None:
            if upstream_inputs.get(nid) is not None:
                upstream[nid] = upstream_inputs[nid]
        executor = executors.get(nid)
        if executor is None:
            failed[nid] = "no executor"
            continue
        try:
            out = executor(upstream)
            if out is None:
                out = {}
            if not isinstance(out, dict):
                out = {"result": out}
            artifacts[nid] = out
            completed.append(nid)
        except Exception as e:  # noqa: BLE001
            failed[nid] = f"{type(e).__name__}: {e}"
            # 环节失败不阻断整链下游：标记后继续（下游拿不到产物会自行降级/跳过）
    return {
        "order": order,
        "completed": completed,
        "skipped": [i for i in completed if i in resume],
        "artifacts": artifacts,
        "failed": failed,
        "ok": not failed,
    }


def wire_orchestrator_stage(workflow: Dict[str, Any],
                            orchestrator_runner: Callable,
                            scenario: str = "",
                            combo: Optional[Dict[str, str]] = None,
                            workdir: str = "./_pipe_8stage",
                            shot_tasks: Optional[List[str]] = None
                            ) -> Dict[str, Callable]:
    """把 8 环节的 video_shot 环节接到 orchestrator（复用三失败路由 + combo 学习）。

    其余环节返回空执行器 stub（产物原样透传，供后续接 comfyui_runner 等实跑）。
    orchestrator_runner: 兼容 orchestrator.run_pipeline 的可调用（对单环节任务列表执行）。
    shot_tasks: 本集镜头 id 列表；缺省取 1 个。
    返回: 环节 id -> 执行器 的 executor_map。
    """
    dataflow = workflow.get("dataflow", [])
    executors: Dict[str, Callable] = {}
    _shots = shot_tasks or ["shot_1"]

    for spec in dataflow:
        nid = spec["id"]
        if nid == "video_shot":
            def _vs(up, _nid=nid, _shots=_shots):
                # 复用 orchestrator：对每个镜头任务跑（含三失败路由 + combo 学习）
                res = orchestrator_runner(
                    all_tasks=list(_shots), workdir=workdir,
                    runner=lambda t: {"ok": True, "video_clip": t},
                    tier=workflow.get("tier", "T1"), node_id="video_shot",
                    scenario=scenario, combo=combo)
                return {"video_clips": res.get("executed", list(_shots)),
                        "failed": res.get("remaining_failed", [])}
            executors[nid] = _vs
        else:
            def _stub(up, _nid=nid):
                # 非视频环节：stub 产物（后续接 comfyui_runner / 真执行器）
                return {"_stage": _nid, "consumed": list(up.keys())}
            executors[nid] = _stub
    return executors


# 分镜专业拆解：景别 / 镜头运动 / 情绪 规则库（短剧爽点镜头语言）
_SHOT_TYPES = [
    ("特写", "缓推", "紧张", "角色面部特写，情绪克制，背景虚化"),
    ("近景", "手持", "压抑", "近景人物动作，手持微晃增强临场"),
    ("中景", "跟随", "推进", "中景跟拍动作，节奏加快"),
    ("全景", "摇臂", "爆发", "全景摇臂展现冲突全貌"),
    ("特写", "急推", "反转", "特写急推抓反转瞬间，浅景深"),
    ("近景", "横移", "铺垫", "近景横移交代环境关系"),
    ("中景", "推拉", "对峙", "中景推拉强化双方对峙张力"),
    ("全景", "升降", "收尾", "全景升降给情绪落点"),
    ("特写", "甩镜", "冲击", "甩镜特写制造视觉冲击"),
    ("中景", "固定", "沉淀", "固定中景留白沉淀情绪"),
]
_EMOTION_KEYWORDS = {
    "反转": ("反转", "翻", "真相", "露馅", "假"),
    "爆发": ("冲", "打", "摔", "砸", "喊", "刀"),
    "紧张": ("看", "盯", "静", "沉默", "阴"),
    "铺垫": ("走", "进", "站", "坐", "拿"),
}


def _classify_emotion(text: str) -> str:
    for emo, kws in _EMOTION_KEYWORDS.items():
        if any(k in (text or "") for k in kws):
            return emo
    return "推进"


# Markdown 元信息行：**类型：** xxx / **集数：** ...
_META_LINE = re.compile(r"^\*\*[^*]{1,12}\*\*\s*[:：]?")
# 表格行 / 分隔线
_TABLE_LINE = re.compile(r"^\|.*\|?$")
_HR_LINE = re.compile(r"^-{3,}$|^_{3,}$|^\*{3,}$")


def _extract_body_lines(script_text: str) -> List[str]:
    """从剧本文本里抽取真正的正文行，剔除 Markdown 排版噪声。

    必须剔除的东西（否则会被当成台词去配音）：
    - 标题行 `# xxx`
    - 元信息行 `**类型：** 职场复仇`
    - 表格行 `| 角色 | 定位 |` / `|------|------|`
    - 分隔线 `---`
    保留：场景标记 `### 【开场】...`、动作描述行、对白行
    """
    out: List[str] = []
    for raw in (script_text or "").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("#"):
            continue
        if _HR_LINE.match(ln):
            continue
        if _TABLE_LINE.match(ln):
            continue
        if _META_LINE.match(ln):
            continue
        out.append(ln)
    return out


# ---------------------------------------------------------------------------
# 角色表解析 + 性别推断（配音分轨靠它，否则全剧一个声音）
# ---------------------------------------------------------------------------
_CHAR_TABLE_HEAD = re.compile(r"^#+\s*角色")
# 表格行：| 林夏 | 主角，27岁，助理 | 黑色中分微卷… |
_ROW = re.compile(r"^\|(.+)\|\s*$")

_FEMALE_HINTS = ("女", "姐", "妈", "姨", "太太", "少女", "姑娘", "闺蜜",
                 "嫂", "婆", "妹", "娘", "女士", "女主", "夫人",
                 # 外形特征
                 "马尾", "连衣裙", "高跟鞋", "长发", "妆容", "睫毛", "口红")
_MALE_HINTS = ("男", "哥", "叔", "爸", "爹", "先生", "少爷", "兄",
               "弟", "爷", "汉子", "丈夫", "小伙",
               # 外形特征
               "油头", "胡茬", "胡须", "络腮胡", "喉结", "寸头", "板寸")
# 名字末字常见性别字（中文短剧角色名，命中率够用）
_FEMALE_NAME_CHARS = set("夏雪晴婷娜丽芳雅玲薇琳媛倩颖洁静梅兰菊竹霞凤燕娟秀珍娥娇媚"
                         "妍蕊璐瑶琦玮蓉蓓薇蕾萱莹莉萍红艳丹彤欣怡雯")
_MALE_NAME_CHARS = set("刚强军伟明杰勇峰涛鹏辉磊超斌鑫浩然健斌豪毅虎龙飞宇")
_AGE = re.compile(r"(\d{1,3})\s*岁")


def _guess_gender(name: str, role: str, desc: str) -> str:
    """角色性别：中文关键词 > 名字末字 > unknown。"""
    # 名字本身也带强信号：「陈姐」的「姐」、「李哥」的「哥」
    blob = f"{name} {role} {desc}"
    for kw in _FEMALE_HINTS:
        if kw in blob:
            return "female"
    for kw in _MALE_HINTS:
        if kw in blob:
            return "male"
    if name:
        last = name[-1]
        if last in _FEMALE_NAME_CHARS:
            return "female"
        if last in _MALE_NAME_CHARS:
            return "male"
    return "unknown"


def parse_characters(script_text: str) -> Dict[str, Dict[str, Any]]:
    """解析剧本「角色设定」表 → {角色名: {role, age, desc, gender}}。

    解析失败返回 {}，上层按 unknown 兜底，不影响出片。
    """
    text = script_text or ""
    lines = text.splitlines()
    start = -1
    for i, ln in enumerate(lines):
        if _CHAR_TABLE_HEAD.match(ln.strip()):
            start = i
            break
    if start < 0:
        return {}

    chars: Dict[str, Dict[str, Any]] = {}
    seen_sep = False
    for ln in lines[start + 1:]:
        t = ln.strip()
        if not t:
            continue  # 表格内空行/表前后空行不算结束
        if t.startswith("#"):
            break  # 遇到下一个标题才算表格结束
        m = _ROW.match(t)
        if not m:
            if chars:
                break
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if not cells or not cells[0]:
            continue
        # 「|------|------|」分隔行
        if all(set(c) <= set("-: ") for c in cells if c):
            seen_sep = True
            continue
        if not seen_sep:
            continue  # 表头行
        name = cells[0]
        if name in ("角色", "") or len(name) > 10:
            continue
        role = cells[1] if len(cells) > 1 else ""
        desc = cells[2] if len(cells) > 2 else ""
        age_m = _AGE.search(f"{role} {desc}")
        chars[name] = {
            "role": role,
            "age": int(age_m.group(1)) if age_m else 0,
            "desc": desc,
            "gender": _guess_gender(name, role, desc),
        }
    return chars


def script_to_shots(script_text: str, shots_per_ep: int = 10,
                    use_llm: bool = False,
                    llm_fn: Optional[Callable] = None) -> Dict[str, Any]:
    """剧本输入解析：script_text → 专业分镜 shots（喂第一环节 script_struct）。

    B 块升级：输出专业分镜提示词（景别+镜头运动+情绪+动作分解），可直接喂
    视频生成。use_llm=True 且提供 llm_fn 时走 LLM 拆解（llm_fn(text)->list[dict]），
    否则用规则化专业拆解（_SHOT_TYPES 轮替 + 情绪分类）。返回结构兼容旧调用。
    """
    lines = _extract_body_lines(script_text)
    shots: List[Dict[str, Any]] = []

    if use_llm and llm_fn is not None:
        try:
            llm_shots = llm_fn(script_text)
            if isinstance(llm_shots, list) and llm_shots:
                for i, s in enumerate(llm_shots[:shots_per_ep]):
                    shots.append({"index": i + 1, "raw": s.get("raw", s.get("text", "")),
                                 "prompt": s.get("prompt", ""), "shot_type": s.get("shot_type", "中景"),
                                 "est_s": s.get("est_s", 5.4)})
        except Exception:
            shots = []  # LLM 失败回退规则拆解
        if len(shots) >= shots_per_ep:
            return {"shots": shots, "shot_count": len(shots), "script_lines": len(lines),
                    "characters": parse_characters(script_text),
                    "mode": "llm"}

    # 规则化专业拆解（默认 / LLM 失败回退）
    raws = lines[:shots_per_ep] if lines else [script_text[:120] or "shot_1"]
    for i, ln in enumerate(raws):
        emo = _classify_emotion(ln)
        st = _SHOT_TYPES[i % len(_SHOT_TYPES)]
        shot_type, motion, emo_label, action = st
        # 情绪命中时覆盖默认景别动作
        if emo == "爆发" and motion != "甩镜":
            shot_type, motion, action = "特写", "急推", "爆发瞬间特写，冲击构图"
        elif emo == "反转" and motion != "甩镜":
            shot_type, motion, action = "特写", "急推", "反转特写，浅景深抓瞬间"
        prompt = f"{shot_type}（{motion}）{action}：{ln[:80]}。情绪基调：{emo}"
        shots.append({"index": i + 1, "raw": ln[:200], "prompt": prompt,
                     "shot_type": shot_type, "motion": motion, "emotion": emo,
                     "est_s": 5.4 if len(ln) < 60 else 12.0})
    while len(shots) < shots_per_ep:
        st = _SHOT_TYPES[len(shots) % len(_SHOT_TYPES)]
        shots.append({"index": len(shots) + 1, "raw": "(空镜头)",
                      "prompt": f"{st[0]}（{st[1]}）{st[3]}：留白过渡镜头。情绪基调：沉淀",
                      "shot_type": st[0], "motion": st[1], "emotion": "沉淀",
                      "est_s": 5.4})
    return {"shots": shots, "shot_count": len(shots), "script_lines": len(lines),
            "characters": parse_characters(script_text),
            "mode": "llm" if use_llm and llm_fn else "rules"}
