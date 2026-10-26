# -*- coding: utf-8 -*-
"""剧本质量自动评估：爽点密度 / 节奏 / 合规性 / 格式。"""
import re
from typing import Any, Dict, List


def check_prohibited_chars(text: str) -> List[Dict[str, Any]]:
    """检查禁止字符（耀/曜）。"""
    issues = []
    for char in ["耀", "曜"]:
        matches = [(m.start(), char) for m in re.finditer(re.escape(char), text)]
        for pos, c in matches:
            # 获取上下文
            start = max(0, pos - 10)
            end = min(len(text), pos + 11)
            context = text[start:end].replace("\n", " ")
            issues.append({
                "type": "prohibited_char",
                "char": c,
                "position": pos,
                "context": f"...{context}...",
                "severity": "error",
                "fix": f"删除或替换字符 '{c}'",
            })
    return issues


def count_hit_points(text: str) -> Dict[str, Any]:
    """统计爽点数量和质量。"""
    hit_keywords = ["打脸", "逆袭", "反转", "震惊", "曝光", "亮出", "底牌",
                    "冷笑", "嘲讽", "啪", "扇", "摔", "砸", "退", "滚",
                    "不", "不行", "不可能", "你竟敢", "放肆", "住手"]
    sweet_keywords = ["温柔", "关心", "温暖", "心疼", "拥抱", "牵手", "微笑",
                      "眼神", "轻声", "轻轻", "点头", "靠"]
    
    hits = sum(1 for kw in hit_keywords if kw in text)
    sweets = sum(1 for kw in sweet_keywords if kw in text)
    
    # 检测明确的爽点标记
    explicit_hits = len(re.findall(r"爽点[①②③④⑤]|高光", text))
    
    return {
        "hit_count": hits,
        "sweet_count": sweets,
        "explicit_hit_marks": explicit_hits,
        "density_score": min(10, (hits + explicit_hits) * 2),
    }


def check_pacing(text: str) -> Dict[str, Any]:
    """检查节奏：开场是否够快，是否有结尾钩子。"""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    
    # 开场检查（前3行是否有冲突词）
    opening_keywords = ["甩", "冷笑", "瞪", "吼", "怒", "抢", "撕", "砸", "踩"]
    opening_text = "\n".join(lines[:8])
    has_opening_conflict = any(kw in opening_text for kw in opening_keywords)
    
    # 结尾钩子检查
    has_hook = "【本集完】" in text or "钩子" in text or "预告" in text
    ending_text = "\n".join(lines[-5:])
    hook_keywords = ["明天", "下集", "原来", "竟然", "等等", "等等！"]
    has_implied_hook = any(kw in ending_text for kw in hook_keywords)
    
    return {
        "opening_fast_enough": has_opening_conflict,
        "has_explicit_hook": has_hook,
        "has_implied_hook": has_implied_hook,
        "pacing_score": (1 if has_opening_conflict else 0) + (1 if (has_hook or has_implied_hook) else 0),
    }


def check_dialogue_length(text: str) -> List[Dict[str, Any]]:
    """检查台词长度（单句≤15字）。"""
    issues = []
    # 匹配台词模式：角色名：台词
    dialogue_pattern = re.compile(r"[\u4e00-\u9fa5]+[：:]\s*(.+?)$")
    for i, line in enumerate(text.split("\n"), 1):
        m = dialogue_pattern.match(line.strip())
        if m:
            dialogue = m.group(1).strip()
            # 去除括号内容
            dialogue = re.sub(r"[（(].+?[）)]", "", dialogue).strip()
            if len(dialogue) > 15:
                issues.append({
                    "type": "long_dialogue",
                    "line": i,
                    "length": len(dialogue),
                    "content": dialogue[:30] + "..." if len(dialogue) > 30 else dialogue,
                    "severity": "warning",
                    "fix": f"台词过长（{len(dialogue)}字），建议精简到15字以内",
                })
    return issues


def check_format_structure(text: str) -> Dict[str, Any]:
    """检查剧本格式完整性。"""
    checks = {
        "has_title": bool(re.search(r"^#\s*《?\s*.{2,}", text, re.MULTILINE)),
        "has_role_table": "## 角色设定" in text or "| 角色 |" in text,
        "has_scenes": bool(re.search(r"###\s*【.+?】", text)),
        "has_hook": "【本集完】" in text,
        "has_hit_list": bool(re.search(r"爽点清单|爽点[①②③]", text)),
        "has_sweet": bool(re.search(r"甜点|甜点点缀", text)),
        "has_shot_prompts": bool(re.search(r"AI绘图提示词|镜头提示", text)),
    }
    checks["format_score"] = sum(checks.values())
    checks["complete"] = all(checks.values())
    return checks


def evaluate_script(text: str, expected_hits: int = 3) -> Dict[str, Any]:
    """综合评估剧本质量。"""
    prohibited = check_prohibited_chars(text)
    hits = count_hit_points(text)
    pacing = check_pacing(text)
    dialogues = check_dialogue_length(text)
    fmt = check_format_structure(text)
    
    # 综合评分（0-100）
    score = 0
    score += hits["density_score"] * 5  # 爽点密度，最高50分
    score += pacing["pacing_score"] * 15  # 节奏，最高30分
    score += fmt["format_score"] * 5  # 格式，最高35分
    score -= len(prohibited) * 20  # 禁止字符扣分
    score -= len(dialogues) * 2  # 长台词扣分
    score = max(0, min(100, score))
    
    # 通过条件
    passed = (
        len(prohibited) == 0
        and hits["density_score"] >= 6
        and pacing["pacing_score"] >= 1
        and fmt["complete"]
    )
    
    return {
        "score": score,
        "passed": passed,
        "prohibited_chars": prohibited,
        "hit_analysis": hits,
        "pacing_analysis": pacing,
        "dialogue_issues": dialogues,
        "format_check": fmt,
        "summary": (
            f"评分 {score}/100 {'✅ 通过' if passed else '❌ 不通过'}，"
            f"爽点密度 {hits['density_score']}/10，"
            f"节奏 {(pacing['pacing_score'])}/2，"
            f"禁止字符 {len(prohibited)} 个"
        ),
    }


def evaluate_file(file_path: str) -> Dict[str, Any]:
    """评估文件。"""
    with open(file_path, encoding="utf-8") as f:
        text = f.read()
    return evaluate_script(text)
