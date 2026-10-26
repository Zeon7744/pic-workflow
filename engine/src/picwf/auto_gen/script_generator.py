# -*- coding: utf-8 -*-
"""用 LLM（或模板兜底）从表单生成剧本 Markdown。"""
import json
import os
from typing import Any, Dict, List, Optional
from .form_schema import FormInput

_ENGINE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
TEMPLATE_DIR = os.path.join(_ENGINE_ROOT, "templates")


def _build_prompt(form: FormInput) -> str:
    chars_desc = "\n".join(
        f"- {c['name']}（{c.get('role','')}，{c.get('gender','')}，{c.get('age_band','')}，特征：{c.get('key_trait','')}）"
        for c in form.characters
    ) or "- 主角（未指定）"
    scenario_map = {
        "workplace_drama": "职场复仇",
        "historical": "古装权谋",
        "romance": "甜宠爱情",
        "thriller": "悬疑推理",
        "fantasy": "都市幻想",
    }
    scenario_cn = scenario_map.get(form.scenario, form.genre)
    return f"""你是一位专业短剧编剧。请根据以下设定生成第1集剧本（Markdown格式）。

【基本信息】
- 剧名：{form.title}
- 题材：{form.genre}（{scenario_cn}）
- 总集数：{form.episodes}集，每集{form.episode_duration}
- 基调：{form.tone}
- 每集爽点数：{form.hit_points_per_ep}，甜点数：{form.sweet_points_per_ep}

【角色设定】
{chars_desc}

【剧情主题】
{form.theme or '根据题材自动生成'}

【输出格式要求】
严格按照以下模板输出，不要有多余说明：

# {form.title} 第1集

## 集概要
（一句话概括本集核心冲突和爽点）

## 角色出场
（列出本集出场角色及简要状态）

## 分镜剧本
### 镜头1
- 场景：（地点）
- 画面描述：（具体画面，≤60字）
- 台词：（角色名：台词内容）
- 爽点类型：（打脸/逆袭/反转/甜宠/悬疑）
- 情绪强度：1-5

### 镜头2
...（按格式继续）

## 本集高光时刻
（列出本集最关键的2-3个爽点镜头号）

请确保：
1. 每集至少{form.hit_points_per_ep}个爽点 + {form.sweet_points_per_ep}个甜点
2. 对话简短，单句≤15字
3. 全程禁止出现"耀/曜"任何字眼
4. 节奏紧凑，开场3秒抓住观众
"""


def _load_template(genre: str) -> str:
    template_map = {
        "职场复仇": "workplace_drama.md",
        "古装权谋": "historical.md",
        "甜宠爱情": "romance.md",
    }
    fname = template_map.get(genre, "workplace_drama.md")
    path = os.path.join(TEMPLATE_DIR, fname)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""


def generate_script_from_form(
    form: FormInput,
    llm_api_base: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_model: str = "deepseek-chat",
    use_llm: bool = True,
) -> str:
    if use_llm and llm_api_base and llm_api_key:
        try:
            import urllib.request
            payload = json.dumps({
                "model": llm_model,
                "messages": [{"role": "user", "content": _build_prompt(form)}],
                "temperature": 0.8,
            }).encode()
            req = urllib.request.Request(
                f"{llm_api_base.rstrip('/')}/v1/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {llm_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
            content = result["choices"][0]["message"]["content"]
            if content and len(content.strip()) > 100:
                return content
        except Exception as e:
            print(f"[auto_gen] LLM 调用失败，回退模板: {e}")

    template = _load_template(form.genre)
    if template:
        filled = template
        filled = filled.replace("{{TITLE}}", form.title)
        filled = filled.replace("{{GENRE}}", form.genre)
        filled = filled.replace("{{EPISODES}}", str(form.episodes))
        filled = filled.replace("{{TONE}}", form.tone)
        if form.characters:
            char_names = ", ".join(c["name"] for c in form.characters[:3])
            filled = filled.replace("{{CHARACTERS}}", char_names)
        return filled

    safe_title = form.title
    return f"""# {safe_title} 第1集

## 集概要
本集讲述主角在关键时刻反击，收获首个爽点。

## 角色出场
{chr(10).join(f'- {c["name"]}（{c.get("role","")}）' for c in form.characters[:3]) if form.characters else '- 主角'}

## 分镜剧本
### 镜头1
- 场景：开场
- 画面描述：主角出场，氛围营造
- 台词：（根据剧情填写）
- 爽点类型：悬念
- 情绪强度：3

### 镜头2
- 场景：冲突升级
- 画面描述：反派施压，主角隐忍
- 台词：（根据剧情填写）
- 爽点类型：铺垫
- 情绪强度：2

### 镜头3
- 场景：高潮反击
- 画面描述：主角亮出底牌，全场震惊
- 台词：（根据剧情填写）
- 爽点类型：打脸
- 情绪强度：5

## 本集高光时刻
镜头3：主角反击瞬间
"""
