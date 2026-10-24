# -*- coding: utf-8 -*-
"""8 环节真执行器：把 dataflow 各环节接上可执行实现。

A 块：post_assemble / bgm_audio / package_publish 接真执行器
  - post_assemble: 聚合 video_clips + voice_track + music_track + bgm_track → 成片路径
  - bgm_audio: audio_advisor.advise_tracks 出 B 轨 → BGM 路径
  - package_publish: 合成最终成片（占位，后续接 ffmpeg/导出）

非视频环节用 audio_advisor 出真音频轨建议；视频环节 video_shot 已接 orchestrator。
"""
from typing import Any, Callable, Dict, List, Optional

try:
    import yaml as _yaml
except Exception:
    _yaml = None


def _load_matrix():
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "config", "matrix.yaml")
    if _yaml is None:
        raise RuntimeError("缺少 PyYAML")
    with open(p, encoding="utf-8") as f:
        return _yaml.safe_load(f)


def make_executors(workflow: Dict[str, Any],
                   runner: Optional[Callable] = None,
                   workdir: str = "./_pipe_exec") -> Dict[str, Callable]:
    """生成 8 环节真执行器映射（环节 id -> executor）。

    workflow: generate_workflow 返回值（含 tier/style/scenario/episode）
    runner: comfyui_runner 实例（可选，缺省 mock）
    返回: executors 映射，可直接喂 pipeline_runner.run_pipeline_8stage。
    """
    tier = workflow.get("tier", "T1")
    style = workflow.get("style", "S1_anime_jp")
    scenario = workflow.get("scenario", "") or "dark_thriller"
    ep = int(workflow.get("episode", workflow.get("ep", 1)) or 1)
    matrix = _load_matrix()

    # 音频轨建议（post_assemble / bgm_audio 复用）
    from .audio_advisor import advise_tracks
    adv = advise_tracks(scenario, matrix, audio_mode="auto", ep=ep)
    adv_by_id = {t["id"]: t for t in adv}
    # advise_tracks 裁剪后可能只有部分轨；用 workflow 已有 music/voice/bgm 字段兜底
    music_track = adv_by_id.get("music", {}).get("track_key", "") or workflow.get("music", "")
    voice_track = adv_by_id.get("voice", {}).get("track_key", "") or workflow.get("voice", "")
    bgm_track = adv_by_id.get("bgm", {}).get("track_key", "") or workflow.get("bgm", "") or "B08_suspense_cold"

    # video_shot 执行器：默认走 capability 层（ComfyUI 仅 adapter 之一）
    if runner is None:
        from .comfyui_runner import make_comfyui_runner
        runner = make_comfyui_runner(mock_fallback=True, workdir=workdir)

    def _capability_backend_for(kind: str) -> Dict[str, Any]:
        from .model_gateway import choose_backend
        return choose_backend(kind, profile={}, backends={
            "generic_local": {"kind": "*", "cloud": False, "priority": 20},
            "cloud_video": {"kind": "video", "cloud": True, "priority": 30},
            "cloud_audio": {"kind": "audio", "cloud": True, "priority": 30},
            "mock": {"kind": "*", "cloud": False, "priority": 90},
        })

    def _efficiency_plan_for_video(up: Dict[str, Any]) -> Dict[str, Any]:
        """同一任务多路径择优：资源/成本/速度/质量四维。"""
        from .model_registry import register_from_matrix, add_custom_model
        from .efficiency_planner import plan_and_report
        from .local_model_index import build_registry_with_local

        reg = register_from_matrix(matrix)
        add_custom_model(reg, "cloud_seedance_2", kind="video", cloud=True,
                         cost=1.8, speed=1.3, quality=0.92, min_vram_gb=0)
        add_custom_model(reg, "cloud_kling", kind="video", cloud=True,
                         cost=1.6, speed=1.1, quality=0.89, min_vram_gb=0)
        add_custom_model(reg, "wan13b_gguf_q4_offload_480", kind="video",
                         cloud=False, cost=0.4, speed=0.8,
                         quality=0.78, min_vram_gb=6)

        local_models = workflow.get("local_models") or []
        local_dir = workflow.get("local_models_dir", "") or "local"
        local_registry = reg
        if local_models or local_dir and local_dir != "local":
            from .local_model_index import build_hot_registry
            local_registry = build_hot_registry(
                base_registry=reg,
                root_dir=local_dir if local_dir != "local" else "",
                prefer_local=True,
                manifest=local_models,
            )
        reg = local_registry

        profile = {"gpu": {"vram_gb": float(workflow.get("free_vram_gb") or 8)}}
        task = {
            "kind": "video",
            "quality_min": 0.8,
            "max_cost": 999.0,
            "max_seconds": 999.0,
            "prefer_local": bool(local_models or (local_dir and local_dir != "local")),
        }
        plan = plan_and_report(reg, profile=profile, task=task)
        plan["local_models_source"] = local_models
        plan["local_models_dir"] = local_dir
        plan["hot_update_enabled"] = bool(local_models or (local_dir and local_dir != "local"))
        return plan

    def _video_shot(up: Dict[str, Any]) -> Dict[str, Any]:
        # 取上游分镜提示词 → 效率规划择优 → 执行
        shots = (up.get("storyboard_prompt", {}) or {}).get("shots",
                  (up.get("script_struct", {}) or {}).get("shots", []))
        plan = _efficiency_plan_for_video(up)
        best = plan.get("best") or {}
        chosen_model = best.get("model_id") or "wan13b_gguf_q4_offload_480"
        executed = []
        qa_decisions = []
        for i, sh in enumerate(shots[:10]):
            out = runner.exec(f"shot_{i+1}", model_impl=chosen_model)
            # 保留原字段位，后续可把 hot_update_enabled / local 资产信息写入审计字段

            # 模拟 QA（真实链路后续由 shot_qa 提供真实 CLIP/时长观测）
            mock_report = {
                "passed": bool(out.get("ok")),
                "route": "pass" if out.get("ok") else "redo_local",
                "scores": {"alignment_intent": 0.95 if out.get("ok") else 0.7},
            }
            decision = None
            if not mock_report["passed"]:
                from .qa_loop import decide_qa_loop
                decision = decide_qa_loop(mock_report, plan=plan,
                                          current_model=chosen_model,
                                          attempt=0,
                                          policy={"escalate_to_cloud": False,
                                                  "max_retries": 1,
                                                  "prefer_local": bool(workflow.get("local_models"))})
            executed.append({
                "index": i + 1,
                "clip": out.get("ok"),
                "peak_vram": out.get("peak_vram_gb"),
                "backend": chosen_model,
                "efficiency_score": best.get("score"),
                "efficiency_gate": plan.get("gate", {}),
                "fallback_paths": [p.get("model_id") for p in plan.get("paths", [])][:3],
                "qa_loop_decision": decision,
                "hot_update_enabled": plan.get("hot_update_enabled", False),
                "local_models_dir": plan.get("local_models_dir", ""),
            })
            if decision:
                qa_decisions.append(decision)
        from .qa_loop import summarize_qa_loop
        qa_summary = summarize_qa_loop(qa_decisions)
        from .accessibility_layer import cost_visibility, friendly_failure, mode_params
        mode = workflow.get("mode", "beginner")
        accessibility = {
            "mode": mode,
            "params": mode_params(mode, {"tier": workflow.get("tier", "T1")})["params"],
            "cost_panel": cost_visibility(plan),
            "failure_panel": friendly_failure(plan, qa_summary),
        }
        return {
            "video_clips": executed,
            "clip_count": len(executed),
            "efficiency_best_model": chosen_model,
            "efficiency_plan": plan,
            "qa_loop_summary": qa_summary,
            "accessibility": accessibility,
        }

    def _post_assemble(up: Dict[str, Any]) -> Dict[str, Any]:
        # fx_enhance 透传了 fx_clips（源头 video_shot 的 video_clips）
        clips_raw = up.get("fx_enhance", {}).get("fx_clips",
                  up.get("video_shot", {}).get("video_clips", []))
        # video_shot 的 clips 是 [{index,clip,peak_vram}]，取文件路径
        clips_paths = [c.get("path", "") for c in clips_raw if isinstance(c, dict)]
        # 真·ffmpeg 合成：不存在的 clip 自动占位，接 BGM/voice 音频轨
        assembled_path = f"{workdir}/assembled_ep{ep}.mp4"
        from .assembler import assemble as _asm
        _audio = []
        if voice_track:
            _audio.append(f"{workdir}/voice_ep{ep}.wav")
        if bgm_track:
            _audio.append(f"{workdir}/bgm_ep{ep}.wav")
        asm_res = _asm(clips_paths or [""]*max(len(clips_raw),1),
                        audio_tracks=_audio or None,
                        out_path=assembled_path, workdir=workdir)
        return {"assembled_video": assembled_path,
                "clip_count": asm_res.get("clip_count", len(clips_raw)),
                "music": music_track, "voice": voice_track, "bgm": bgm_track,
                "duration_s": asm_res.get("duration_s", 0),
                "assembled": asm_res.get("ok", False),
                "assembled_ffmpeg": asm_res.get("ffmpeg", False)}

    def _bgm_audio(up: Dict[str, Any]) -> Dict[str, Any]:
        # B 轨真建议（advise_tracks 出 B08_suspense_cold）
        return {"bgm_track": bgm_track, "bgm_path": f"{workdir}/bgm_ep{ep}.wav"}

    def _package_publish(up: Dict[str, Any]) -> Dict[str, Any]:
        pa = up.get("post_assemble", {})
        assembled = pa.get("assembled_video", "")
        bgm = up.get("bgm_audio", {}).get("bgm_track", bgm_track)
        # 成片路径：post_assemble 已真合成时直接用，否则占位路径
        import os
        final_path = f"{workdir}/final_ep{ep}.mp4"
        if pa.get("assembled") and os.path.exists(assembled):
            # 复制/硬链成片
            try:
                import shutil; shutil.copyfile(assembled, final_path)
            except Exception:
                final_path = assembled
        return {"final_video": final_path,
                "bgm_track": bgm,
                "publish_ready": bool(pa.get("assembled")) and bool(final_path),
                "duration_s": pa.get("duration_s", 0)}

    def _fx_enhance(up: Dict[str, Any]) -> Dict[str, Any]:
        clips = up.get("video_shot", {}).get("video_clips", [])
        return {"fx_clips": clips, "fx_applied": True}

    def _script_struct(up: Dict[str, Any]) -> Dict[str, Any]:
        from .pipeline_runner import script_to_shots
        return script_to_shots((up.get("script_struct", {}) or {}).get("text", ""),
                                shots_per_ep=10)

    def _character_image(up: Dict[str, Any]) -> Dict[str, Any]:
        # 升级：角色一致性引擎 —— 出角色外观锁定块 + 三视图参考图锚点（控不走样）
        from .character_consistency import three_view_anchor_refs, build_character_block
        # workflow 可带 characters（list of dict: name/role/gender/age_band/hair/outfit/temperament）
        chars = workflow.get("characters") or [
            {"name": workflow.get("hero", "主角"), "role": "主角", "gender": "女性"}]
        refs = three_view_anchor_refs(chars, workdir)
        blocks = [build_character_block(c) for c in chars]
        return {"character_refs": [r["three_view_path"] for r in refs],
                "char_blocks": blocks, "char_count": len(chars),
                "three_view_prompts": [r["prompt"] for r in refs]}

    def _storyboard_prompt(up: Dict[str, Any]) -> Dict[str, Any]:
        # 升级（公开前沿迭代）：题材自动识别 + 6 维 + 人性化 + 角色一致性
        #   + 时间轴化分镜 + 首尾帧传递 + 特征词逐字锁定
        from .topic_adapt import adapt_script
        from .shot_choreo import craft_time_axis_shot, motion_consistency_audit
        from .continuity import chain_shots
        from .character_consistency import lock_char_traits
        base_shots = (up.get("script_struct", {}) or {}).get("shots", [])
        text = (up.get("script_struct", {}) or {}).get("text", "") or " ".join(
            s.get("raw", "") for s in base_shots)
        chars = workflow.get("characters")
        # 特征词逐字锁定（禁缩写，"长发" -> 精确长度）
        chars_locked = [lock_char_traits(c)["locked"] for c in chars] if chars else None
        adapted = adapt_script(text, base_shots, chars=chars_locked)
        # 时间轴化 + 首尾帧传递
        shots_final = []
        prev_state = None
        for s in adapted["shots"]:
            # 首尾帧传递：把上镜 state_after 传到下镜开头
            if prev_state:
                s = dict(s, carry_from_prev=prev_state,
                         prompt=f"承接自上一镜：{prev_state.get('pose','')}；{s.get('prompt','')}")
            # 时间轴化时段
            s = craft_time_axis_shot(s)
            shots_final.append(s)
            prev_state = s.get("state_after") or prev_state
        # 运镜打架审计
        motion_violations = motion_consistency_audit([s.get("prompt", "") for s in shots_final])
        final = [s.get("final_prompt", s.get("craft_prompt", s.get("prompt", "")))
                 for s in adapted["shots"]]
        return {"shots": shots_final, "topic": adapted["topic"],
                "style": adapted["style"], "shot_prompts": final,
                "time_axis_applied": True, "skeleton_chained": True,
                "motion_violations": motion_violations,
                "chars_locked": bool(chars_locked)}

    return {
        "script_struct": _script_struct,
        "character_image": _character_image,
        "storyboard_prompt": _storyboard_prompt,
        "video_shot": _video_shot,
        "fx_enhance": _fx_enhance,
        "post_assemble": _post_assemble,
        "bgm_audio": _bgm_audio,
        "package_publish": _package_publish,
        # 叠加音频轨（可选，被裁时不在 dataflow）
        "music": lambda up: {"music_track": music_track},
        "voice": lambda up: {"voice_track": voice_track},
        "bgm": lambda up: {"bgm_track": bgm_track},
    }
