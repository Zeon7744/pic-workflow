# -*- coding: utf-8 -*-
"""批量出片：一次提交多集表单，并行生成。"""
import os
import asyncio
from typing import Any, Dict, List, Optional
from .auto_gen import FormInput, run_auto_pipeline

async def generate_episode(form: FormInput, ep_num: int, workdir: str) -> Dict[str, Any]:
    """生成单集。"""
    import tempfile
    ep_workdir = os.path.join(workdir, f"ep{ep_num}")
    ep_form = FormInput(
        title=f"{form.title} 第{ep_num}集",
        genre=form.genre,
        episodes=1,
        episode_duration=form.episode_duration,
        theme=form.theme,
        tone=form.tone,
        characters=form.characters,
        style_key=form.style_key,
        tier=form.tier,
        cloud_model=form.cloud_model,
    )
    return await asyncio.to_thread(
        run_auto_pipeline, ep_form, ep_workdir,
        use_llm=bool(os.getenv("LLM_API_KEY")),
    )


async def batch_generate(
    form: FormInput,
    workdir: str = "./_batch_output",
    max_concurrent: int = 3,
) -> Dict[str, Any]:
    """批量生成多集：并发控制，返回每集结果。"""
    os.makedirs(workdir, exist_ok=True)
    sem = asyncio.Semaphore(max_concurrent)

    async def _with_sem(ep_num: int):
        async with sem:
            return await generate_episode(form, ep_num, workdir)

    tasks = [asyncio.create_task(_with_sem(i+1)) for i in range(form.episodes)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success = [r for r in results if isinstance(r, dict) and r.get("form_valid")]
    failed = [r for r in results if isinstance(r, dict) and not r.get("form_valid")]
    errors = [r for r in results if isinstance(r, BaseException)]

    return {
        "total": form.episodes,
        "success": len(success),
        "failed": len(failed),
        "errors": len(errors),
        "results": results,
        "workdir": workdir,
    }
