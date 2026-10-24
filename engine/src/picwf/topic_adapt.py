# -*- coding: utf-8 -*-
"""topic_adapt：题材自动识别（覆盖面广 的智能入口）。

从剧本文本/台词自动判题材，免去手工指定。识别出 topic 后交给
prompt_craft.build_shot_prompt(topic=...) 自动切色调/光位/人性化基调。

支持题材：现实 / 古装 / 科幻 / 悬疑 / 甜宠 / 恐怖。
"""
from typing import Dict, Any, Optional

# 题材 → 关键词权重表（命中计分，取最高）
_TOPIC_KEYWORDS = {
    "古装": ["古装", "汉服", "公子", "小姐", "殿", "宫", "王爷", "太子", "皇帝",
             "本宫", "本殿", "侍", "剑", "江湖", "武林", "客栈", "镖", "朝", "陛下",
             "娘娘", "将军", "丞相", "御", "簪", "发髻"],
    "科幻": ["科幻", "未来", "2099", "2199", "3024", "太空", "飞船", "机甲", "AI",
             "机械", "全息", "量子", "星际", "银河", "克隆", "芯片", "机器人", "赛博",
             "霓虹都市", "外星", "次元", "异世界科技"],
    "悬疑": ["悬疑", "侦探", "案件", "死者", "凶", "监控", "证物", "失踪", "尸体",
             "血迹", "凶手", "谜", "真相", "线索", "审讯", "警方", "调查", "谜团", "疑点"],
    "恐怖": ["恐怖", "鬼", "阴森", "棺材", "冥", "血月", "尸", "僵尸", "灵异",
             "怨", "咒", "墓", "荒宅", "深夜", "鬼屋", "咒", "尸"],
    "甜宠": ["甜", "宠", "恋爱", "表白", "暗恋", "初恋", "婚礼", "求婚", "亲亲",
             "抱抱", "牵手", "心动", "甜蜜", "撒娇", "壁咚", "抱抱", "抱抱"],
}


def detect_topic(text: str) -> str:
    """从文本判题材。命中计分取最高；全不中默认 现实（最通用兜底）。"""
    text = (text or "")
    scores = {t: 0 for t in _TOPIC_KEYWORDS}
    for topic, kws in _TOPIC_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[topic] += text.count(kw)
    best = max(scores, key=lambda t: scores[t])
    if scores[best] == 0:
        return "现实"
    return best


def adapt_shot_style(topic: str, shot: Dict[str, Any]) -> Dict[str, Any]:
    """按题材给单镜返回风格建议（色调/光位/人性化基调），供 prompt_craft 使用。

    这里只做题材→风格的轻映射（prompt_craft 内部 _TOPIC_STYLE 是完整实现，
    本函数作为对外独立入口 + 便于单测）。
    """
    from .prompt_craft import _TOPIC_STYLE, _TOPIC_DEFAULT
    style = _TOPIC_STYLE.get(topic, _TOPIC_DEFAULT)
    return {
        "topic": topic,
        "palette": style.get("palette", "自然"),
        "light": style.get("light", "自然光"),
        "human_base": style.get("human", ""),
    }


def adapt_script(text: str, shots: list,
                 chars: Optional[list] = None) -> Dict[str, Any]:
    """一站式：识别题材 → 批量给 shots 补 6 维 + 角色一致性 prompt。

    返回 {"topic": ..., "shots": [...带 craft_prompt/final_prompt...], "style": {...}}
    """
    from .prompt_craft import craft_all_shots
    topic = detect_topic(text)
    crafted = craft_all_shots(shots, topic=topic, chars=chars)
    return {"topic": topic, "shots": crafted, "style": adapt_shot_style(topic, {})}
