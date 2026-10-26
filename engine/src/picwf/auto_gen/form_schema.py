# -*- coding: utf-8 -*-
"""表单字段定义与校验。"""
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

FORM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["genre", "title", "episodes"],
    "properties": {
        "title": {"type": "string", "minLength": 2, "maxLength": 50},
        "genre": {
            "type": "string",
            "enum": ["职场复仇", "古装权谋", "甜宠爱情", "悬疑推理", "都市幻想", "历史传奇"],
        },
        "episodes": {"type": "integer", "minimum": 1, "maximum": 50},
        "episode_duration": {"type": "string", "enum": ["30秒", "1分钟", "2分钟"], "default": "1分钟"},
        "theme": {"type": "string", "maxLength": 100},
        "tone": {
            "type": "string",
            "enum": ["爽感强烈", "节奏紧凑", "温情治愈", "悬疑紧张", "喜剧轻松"],
            "default": "爽感强烈",
        },
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string", "enum": ["主角", "反派", "配角", "助手"]},
                    "gender": {"type": "string", "enum": ["男", "女"]},
                    "age_band": {"type": "string", "enum": ["少年", "青年", "中年", "老年"]},
                    "key_trait": {"type": "string", "maxLength": 30},
                },
                "required": ["name", "role"],
            },
            "minItems": 1,
            "maxItems": 5,
        },
        "style_key": {
            "type": "string",
            "enum": [
                "S1_anime_jp", "S2_korea", "S3_cn_shuimo",
                "S4_realistic", "S5_mmd", "S6_shounen",
            ],
            "default": "S1_anime_jp",
        },
        "tier": {
            "type": "string",
            "enum": ["T0", "T1", "T2", "cloud"],
            "default": "T1",
        },
        "cloud_model": {"type": "string", "enum": ["wan", "kling", "seedream"]},
        "scenario": {
            "type": "string",
            "enum": ["workplace_drama", "historical", "romance", "thriller", "fantasy"],
        },
        "hit_points_per_ep": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
        "sweet_points_per_ep": {"type": "integer", "minimum": 0, "maximum": 2, "default": 1},
    },
}

@dataclass
class FormInput:
    title: str
    genre: str
    episodes: int
    episode_duration: str = "1分钟"
    theme: str = ""
    tone: str = "爽感强烈"
    characters: List[Dict[str, str]] = field(default_factory=list)
    style_key: str = "S1_anime_jp"
    tier: str = "T1"
    cloud_model: Optional[str] = None
    scenario: Optional[str] = None
    hit_points_per_ep: int = 3
    sweet_points_per_ep: int = 1

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormInput":
        return cls(
            title=data["title"],
            genre=data["genre"],
            episodes=data["episodes"],
            episode_duration=data.get("episode_duration", "1分钟"),
            theme=data.get("theme", ""),
            tone=data.get("tone", "爽感强烈"),
            characters=data.get("characters", []),
            style_key=data.get("style_key", "S1_anime_jp"),
            tier=data.get("tier", "T1"),
            cloud_model=data.get("cloud_model"),
            scenario=data.get("scenario"),
            hit_points_per_ep=data.get("hit_points_per_ep", 3),
            sweet_points_per_ep=data.get("sweet_points_per_ep", 1),
        )


def validate_form(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    for k in FORM_SCHEMA.get("required", []):
        if k not in data:
            errors.append(f"缺少必填字段: {k}")
    props = FORM_SCHEMA.get("properties", {})
    if "title" in data:
        t = data["title"]
        if not isinstance(t, str) or len(t) < 2:
            errors.append("title 至少2个字符")
        if len(t) > 50:
            errors.append("title 不超过50字符")
    if "genre" in data and data["genre"] not in props.get("genre", {}).get("enum", []):
        errors.append(f"genre 不合法: {data['genre']}")
    if "episodes" in data:
        ep = data["episodes"]
        if not isinstance(ep, int) or ep < 1 or ep > 50:
            errors.append("episodes 范围 1-50")
    if "characters" in data:
        chars = data["characters"]
        if not isinstance(chars, list) or len(chars) < 1:
            errors.append("characters 至少1个")
        for i, c in enumerate(chars):
            if "name" not in c:
                errors.append(f"characters[{i}] 缺少 name")
            if "role" not in c:
                errors.append(f"characters[{i}] 缺少 role")
    return errors
