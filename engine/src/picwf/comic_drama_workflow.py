# -*- coding: utf-8 -*-
"""comic_drama_workflow: 漫剧专用 ComfyUI 工作流模板加载与渲染。

定位(白皇 2026-10-28): 给 ComfyUI 提供漫剧工作流, 用测试好的数据先做互通。

职责:
- 从 config/comfyui/comic_drama/*.json 加载预置工作流模板
- 按参数(角色/分镜/运动)渲染成"可直接 POST 给 ComfyUI /prompt 的真实节点图"
- 提供模板注册表 + 渲染 + 档位兼容性检查, 供 comfyui_runner / workflow_explorer 复用

模板是数据不是代码: 新增一类漫剧工作流只需加一个 JSON, 无需改引擎代码。
"""
import json
import os
from typing import Any, Dict, List, Optional

TEMPLATE_DIR_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "comfyui", "comic_drama")

KNOWN_COMIC_WORKFLOWS = ["character_sheet", "storyboard", "motion"]


def template_dir():
    return os.environ.get("COMIC_TEMPLATE_DIR", "").strip() or TEMPLATE_DIR_DEFAULT


def list_available_templates(dir_path=None):
    d = dir_path or template_dir()
    if not os.path.isdir(d):
        return []
    return [f[:-5] for f in sorted(os.listdir(d)) if f.endswith(".json")]


def load_template(name, dir_path=None):
    d = dir_path or template_dir()
    p = os.path.join(d, name + ".json")
    if not os.path.exists(p):
        raise FileNotFoundError("未找到漫剧工作流模板 %s, 可用: %s" % (name, list_available_templates(d)))
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _first_word(text):
    parts = (text or "").split()
    return parts[0] if parts else "x"


def _render_node_inputs(inputs, ctx):
    out = {}
    for k, v in inputs.items():
        if isinstance(v, str) and "{{" in v:
            s = v
            for key, val in ctx.items():
                s = s.replace("{{" + key + "}}", str(val))
            for src in ("character_prompt", "shot_prompt", "motion_prompt"):
                s = s.replace("{{" + src + "|first_word}}", _first_word(ctx.get(src, "")))
            out[k] = s
        else:
            out[k] = v
    return out


def render_workflow(name, overrides=None, tier="T3", dir_path=None):
    """渲染一份可直接 POST 给 ComfyUI /prompt 的漫剧工作流。"""
    tpl = load_template(name, dir_path)
    ctx = dict(tpl.get("inputs", {}))
    ctx.update(overrides or {})
    ctx.setdefault("variant", 0)
    ctx.setdefault("frame", 0)
    rendered = {}
    for node_id, node in tpl.get("workflow", {}).items():
        rendered[str(node_id)] = {
            "class_type": node.get("class_type"),
            "inputs": _render_node_inputs(node.get("inputs", {}), ctx),
        }
    warnings = []
    tier_compat = tpl.get("tier_compat") or []
    if tier_compat and tier not in tier_compat:
        warnings.append("模板 %s 推荐档位 %s, 当前 %s 可能显存不足, 建议降档或用云端兜底 %s"
                       % (name, tier_compat, tier, tpl.get("cloud_fallback", "")))
    return {
        "workflow": rendered,
        "name": tpl.get("name", name),
        "meta": {
            "template": name,
            "outputs": tpl.get("outputs", []),
            "lora_hook": bool(tpl.get("lora_hook", False)),
            "cloud_fallback": tpl.get("cloud_fallback"),
            "consistency_score_target": tpl.get("consistency_score_target"),
        },
        "warnings": warnings,
        "rendered_inputs": ctx,
    }


def build_prompt_payload(name, overrides=None, tier="T3"):
    """生成可直接 POST 给 ComfyUI /prompt 的请求体: {"prompt": {...}}。"""
    r = render_workflow(name, overrides, tier)
    return {"prompt": r["workflow"], "template": r["name"], "warnings": r["warnings"]}


def validate_rendered(rendered):
    """校验渲染结果是否残留未替换占位符 / 悬空节点引用。返回问题列表(空=OK)。"""
    issues = []
    for nid, node in rendered.items():
        inputs = node.get("inputs", {})
        for k, v in inputs.items():
            if isinstance(v, str) and "{{" in v:
                issues.append("节点%s.%s 残留占位符: %s" % (nid, k, v))
            if isinstance(v, list) and len(v) >= 1 and isinstance(v[0], str):
                if v[0] not in rendered:
                    issues.append("节点%s.%s 引用不存在的节点 %s" % (nid, k, v[0]))
    return issues


def get_registry(dir_path=None):
    reg = {}
    for name in list_available_templates(dir_path):
        try:
            tpl = load_template(name, dir_path)
            reg[name] = {
                "name": name,
                "description": tpl.get("description", ""),
                "tier_compat": tpl.get("tier_compat", []),
                "outputs": tpl.get("outputs", []),
                "cloud_fallback": tpl.get("cloud_fallback"),
                "lora_hook": bool(tpl.get("lora_hook", False)),
            }
        except Exception:
            reg[name] = {"name": name, "error": "模板解析失败"}
    return reg


__all__ = ["TEMPLATE_DIR_DEFAULT", "KNOWN_COMIC_WORKFLOWS", "template_dir",
           "list_available_templates", "load_template", "render_workflow",
           "build_prompt_payload", "validate_rendered", "get_registry"]
