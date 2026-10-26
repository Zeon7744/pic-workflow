# -*- coding: utf-8 -*-
"""表单 → LLM → 剧本 → 引擎 全自动链路。"""
import os
import json
from typing import Any, Dict, Optional
from .form_schema import FormInput, validate_form
from .script_generator import generate_script_from_form


def run_auto_pipeline(
    form: FormInput,
    workdir: str = "./_auto_output",
    llm_api_base: Optional[str] = None,
    llm_api_key: Optional[str] = None,
    llm_model: str = "deepseek-chat",
    use_llm: bool = True,
    save_script: bool = True,
) -> Dict[str, Any]:
    """全流程：表单校验 → 剧本生成 → 引擎出片。
    
    返回: {
        "form_valid": bool,
        "form_errors": list,
        "script_path": str,
        "script_text": str,
        "pipeline_report": dict,
        "final_video": str,
        "cloud_model_used": str,
    }
    """
    result: Dict[str, Any] = {
        "form_valid": True,
        "form_errors": [],
        "script_path": "",
        "script_text": "",
        "pipeline_report": {},
        "final_video": "",
        "cloud_model_used": form.cloud_model or "",
    }
    
    # Step 1: 表单校验
    errors = validate_form({
        "title": form.title,
        "genre": form.genre,
        "episodes": form.episodes,
        "characters": form.characters,
        "style_key": form.style_key,
        "tier": form.tier,
    })
    if errors:
        result["form_valid"] = False
        result["form_errors"] = errors
        return result
    
    # Step 2: 生成剧本
    script_text = generate_script_from_form(
        form,
        llm_api_base=llm_api_base,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        use_llm=use_llm,
    )
    result["script_text"] = script_text
    
    # Step 3: 保存剧本
    os.makedirs(workdir, exist_ok=True)
    safe_title = form.title.replace("/", "_").replace(" ", "_")
    script_path = os.path.join(workdir, f"剧本_{safe_title}_第1集.md")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_text)
    result["script_path"] = script_path
    
    if not save_script:
        # 只生成剧本，不跑引擎
        result["pipeline_report"] = {"skipped": "save_script=False"}
        return result
    
    # Step 4: 跑引擎
    try:
        from ..pipeline_cli import run as pipeline_run
        engine_args = {
            "script_path": script_path,
            "tier": form.tier if form.tier != "cloud" else "T0",
            "style": form.style_key,
            "scenario": form.scenario or _genre_to_scenario(form.genre),
            "ep": form.episodes,
            "workdir": os.path.join(workdir, "engine_output"),
            "cloud_model": form.cloud_model or "",
        }
        report = pipeline_run(**engine_args)
        result["pipeline_report"] = report
        result["final_video"] = report.get("final_video", "")
    except Exception as e:
        result["pipeline_report"] = {"error": str(e)}
    
    return result


def _genre_to_scenario(genre: str) -> str:
    mapping = {
        "职场复仇": "workplace_drama",
        "古装权谋": "historical",
        "甜宠爱情": "romance",
        "悬疑推理": "thriller",
        "都市幻想": "fantasy",
        "历史传奇": "historical",
    }
    return mapping.get(genre, "workplace_drama")
