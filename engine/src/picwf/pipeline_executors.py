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

    # video_shot 执行器：用 comfyui_runner 跑
    if runner is None:
        from .comfyui_runner import make_comfyui_runner
        runner = make_comfyui_runner(mock_fallback=True, workdir=workdir)

    def _video_shot(up: Dict[str, Any]) -> Dict[str, Any]:
        # 取上游分镜提示词 → 跑视频镜头
        shots = (up.get("storyboard_prompt", {}) or {}).get("shots",
                  (up.get("script_struct", {}) or {}).get("shots", []))
        executed = []
        for i, sh in enumerate(shots[:10]):  # 限制 10 镜头/集
            out = runner.exec(f"shot_{i+1}", model_impl="wan13b_gguf_q4_offload_480")
            executed.append({"index": i + 1, "clip": out.get("ok"),
                            "peak_vram": out.get("peak_vram_gb")})
        return {"video_clips": executed, "clip_count": len(executed)}

    def _post_assemble(up: Dict[str, Any]) -> Dict[str, Any]:
        # fx_enhance 透传了 fx_clips（源头 video_shot 的 video_clips）
        clips = up.get("fx_enhance", {}).get("fx_clips",
                  up.get("video_shot", {}).get("video_clips", []))
        return {"assembled_video": f"{workdir}/assembled_ep{ep}.mp4",
                "clip_count": len(clips), "music": music_track,
                "voice": voice_track, "bgm": bgm_track}

    def _bgm_audio(up: Dict[str, Any]) -> Dict[str, Any]:
        # B 轨真建议（advise_tracks 出 B08_suspense_cold）
        return {"bgm_track": bgm_track, "bgm_path": f"{workdir}/bgm_ep{ep}.wav"}

    def _package_publish(up: Dict[str, Any]) -> Dict[str, Any]:
        assembled = up.get("post_assemble", {}).get("assembled_video", "")
        bgm = up.get("bgm_audio", {}).get("bgm_track", bgm_track)
        return {"final_video": f"{workdir}/final_ep{ep}.mp4",
                "bgm_track": bgm, "publish_ready": bool(assembled)}

    def _fx_enhance(up: Dict[str, Any]) -> Dict[str, Any]:
        clips = up.get("video_shot", {}).get("video_clips", [])
        return {"fx_clips": clips, "fx_applied": True}

    def _script_struct(up: Dict[str, Any]) -> Dict[str, Any]:
        from .pipeline_runner import script_to_shots
        return script_to_shots((up.get("script_struct", {}) or {}).get("text", ""),
                                shots_per_ep=10)

    def _character_image(up: Dict[str, Any]) -> Dict[str, Any]:
        return {"character_refs": [f"{workdir}/char_{style}.png"]}

    def _storyboard_prompt(up: Dict[str, Any]) -> Dict[str, Any]:
        # B 块：用专业分镜 prompt（script_struct 产物已含 prompt 字段）
        shots = (up.get("script_struct", {}) or {}).get("shots", [])
        return {"shots": shots,
                "shot_prompts": [s.get("prompt", s.get("raw", "")) for s in shots]}

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
