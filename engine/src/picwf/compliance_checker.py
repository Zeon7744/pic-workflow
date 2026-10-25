# -*- coding: utf-8 -*-
"""compliance_checker：内容合规/版权/肖像权/平台红线自检（行业前3的"合法性"维度）。

AI 短剧出片前过不了合规就发不了。本模块做"发布前合规门"，四个检查维度：

1. content_check(texts) -> 敏感内容（暴力/低俗/政治/未成年人保护 红线词）扫描
2. copyright_check(assets) -> 素材版权（LoRA/字体/BGM 是否自有或授权，商用标注）
3. portrait_check(chars) -> 肖像权（真人角色是否获授权/虚构标注），行业前3必查
4. platform_redline(scene, channel) -> 平台红线（抖音/红果各平台特定禁令）
每个返回 {passed, issues:[{type, level, detail, action}]}，aggregate 汇总成
可发布的合规报告。level: block(阻断发布) / warn(需人工) / info。

设计：纯规则离线（红线词表 + 授权字段检查），不联网；给"素材是否合规可发布"
一个可审计的结论，这是引擎做 MCN 级出品（帮白皇跑通红果发布）的关键门槛。
"""
from typing import Dict, List, Any, Optional

# 红线词表（可按平台追加）
BLOCK_WORDS = {
    "violence": ["血腥", "断肢", "肢解", "自残"],
    "minor": ["未成年", "儿童出演", "18岁以下"],
    "illegal": ["赌博", "吸毒", "贩毒", "枪支走私"],
    "political": ["涉政", "国旗不当使用"],
}
WARN_WORDS = {
    "low_class": ["擦边", "暗示性", "裸露"],
    "scare": ["惊悚过头", "血腥暗示"],
}

# 平台红线（各平台特有条款，示意集，实机按平台官方规则更新）
PLATFORM_REDLINES = {
    "douyin": ["禁止未成年出镜", "禁止医疗功效承诺", "禁止虚假宣传"],
    "hongguo": ["短剧备案号", "禁止诱导付费套路", "价值观导向要求"],
    "bilibili": ["版权完整", "禁止搬运"],
}


def _scan(texts: List[str], word_map: Dict[str, List[str]]) -> List[Dict[str, Any]]:
    issues = []
    joined = " ".join(texts or [])
    for cat, words in word_map.items():
        hit = [w for w in words if w in joined]
        if hit:
            issues.append({"type": "content", "category": cat,
                           "level": "block" if cat in ("violence", "minor", "illegal", "political") else "warn",
                           "hits": hit,
                           "detail": f"{cat} 命中 {len(hit)} 词: {hit}",
                           "action": "block 词必须改写/删镜，warn 词需人工复核"})
    return issues


def content_check(texts: List[str]) -> Dict[str, Any]:
    """敏感内容扫描（红线词）。"""
    issues = _scan(texts, BLOCK_WORDS) + _scan(texts, WARN_WORDS)
    block = any(i["level"] == "block" for i in issues)
    return {"passed": not block, "issues": issues,
            "block_count": sum(1 for i in issues if i["level"] == "block")}


def copyright_check(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """素材版权检查：LoRA/字体/BGM 是否自有或已授权。

    assets: [{type, name, license, owner, commercial_ok}]
    缺 license / owner 非自有 / commercial_ok=False → 不能商用发布。
    """
    issues = []
    own_owner = {"self", "hookforge", "baibai", "zeon7744"}
    for a in assets:
        lic = (a.get("license") or "").lower()
        owner = (a.get("owner") or "").lower()
        ok = a.get("commercial_ok")
        if not lic:
            issues.append({"type": "copyright", "asset": a.get("name", a.get("type")),
                           "level": "block", "detail": "缺 license 声明", "action": "补授权来源"})
        elif owner and owner not in own_owner and not a.get("licensed"):
            issues.append({"type": "copyright", "asset": a.get("name", a.get("type")),
                           "level": "warn", "detail": f"第三方素材 owner={owner} 未标授权",
                           "action": "确认商用授权"})
        elif ok is False:
            issues.append({"type": "copyright", "asset": a.get("name", a.get("type")),
                           "level": "block", "detail": "商用授权未覆盖 commercial_ok=False",
                           "action": "换自有/授权素材"})
    block = any(i["level"] == "block" for i in issues)
    return {"passed": not block, "issues": issues, "checked": len(assets)}


def portrait_check(chars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """肖像权检查：真人角色是否获授权 / 是否虚构标注。

    chars: [{name, based_on_real_person, consent_obtained, fictional}]
    真人未授权 -> block；纯虚构标注 -> 通过。
    """
    issues = []
    for c in chars:
        real = c.get("based_on_real_person")
        if real and not c.get("consent_obtained"):
            issues.append({"type": "portrait", "char": c.get("name"),
                           "level": "block", "detail": "基于真人但未获肖像授权",
                           "action": "改虚构设定或取得书面授权"})
        if real and not c.get("fictional"):
            issues.append({"type": "portrait", "char": c.get("name"),
                           "level": "warn", "detail": "真人角色未标注虚构声明",
                           "action": "加'本角色纯属虚构'声明"})
    block = any(i["level"] == "block" for i in issues)
    return {"passed": not block, "issues": issues, "checked": len(chars)}


def platform_redline_check(platform: str, content_summary: str = "") -> Dict[str, Any]:
    """平台特定红线检查。"""
    reds = PLATFORM_REDLINES.get(platform, [])
    issues = []
    for r in reds:
        issues.append({"type": "platform", "platform": platform, "level": "info",
                       "detail": r, "action": "发布前确认符合该条款"})
    # 内容命中的平台词
    hit = [r for r in reds if r in content_summary]
    if hit:
        for r in hit:
            issues.append({"type": "platform", "platform": platform, "level": "warn",
                           "detail": f"内容疑似触'{r}'", "action": "人工复核"})
    return {"platform": platform, "issues": issues,
            "redlines": reds, "passed": True}


def aggregate_compliance(content: Dict, copyright_r: Dict, portrait: Dict,
                         platform: Optional[Dict] = None) -> Dict[str, Any]:
    """汇总合规报告：能否发布。"""
    all_issues = (content.get("issues", []) + copyright_r.get("issues", [])
                  + portrait.get("issues", []) + (platform.get("issues", []) if platform else []))
    block = [i for i in all_issues if i.get("level") == "block"]
    warn = [i for i in all_issues if i.get("level") == "warn"]
    publishable = len(block) == 0
    return {
        "publishable": publishable,
        "block_count": len(block), "warn_count": len(warn),
        "blocking": block, "warnings": warn,
        "dims": {
            "content": content.get("passed"), "copyright": copyright_r.get("passed"),
            "portrait": portrait.get("passed"),
            "platform": (platform or {}).get("passed"),
        },
        "note": "全部 block 项清零才可发布；warn 项需人工复核签字",
    }
