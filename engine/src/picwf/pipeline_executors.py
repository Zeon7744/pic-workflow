# -*- coding: utf-8 -*-
"""8 环节真执行器：把 dataflow 各环节接上可执行实现。

A 块：post_assemble / bgm_audio / package_publish 接真执行器
  - post_assemble: 聚合 video_clips + voice_track + music_track + bgm_track → 成片路径
  - bgm_audio: audio_advisor.advise_tracks 出 B 轨 → BGM 路径
  - package_publish: 合成最终成片（占位，后续接 ffmpeg/导出）

非视频环节用 audio_advisor 出真音频轨建议；视频环节 video_shot 已接 orchestrator。
"""
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

# 云端模型路由（API Key 配置后才启用）
try:
    from .cloud_api import has_key, get_key
    _HAS_CLOUD_API = True
except Exception:
    _HAS_COUND_API = False
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


def _ensure_char_refs(characters: Optional[Dict[str, Any]],
                      workdir: str) -> Dict[str, str]:
    """为每个角色出定妆照，返回 {名字: 图片URL}，落盘缓存避免重复出图。

    定妆照是分镜图 i2i 的视觉锚点：只靠文字描述，同一个角色每个镜头都会变脸；
    拿定妆照做参考图，脸型/发型/服装才稳定。
    """
    if not characters:
        return {}
    from .cloud_api import agnes_image
    refs: Dict[str, str] = {}
    for name, c in characters.items():
        if not name:
            continue
        cache = f"{workdir}/_charref_{name}.json"
        if os.path.isfile(cache):
            try:
                with open(cache, encoding="utf-8") as f:
                    d = json.load(f)
                if d.get("url") and d.get("path") and os.path.isfile(d["path"]):
                    refs[name] = d["url"]
                    continue
            except Exception:
                pass
        age = c.get("age")
        gender = {"female": "女性", "male": "男性"}.get(
            str(c.get("gender") or "").lower(), "人物")
        head = f"{name}，{age}岁{gender}" if age else f"{name}，{gender}"
        desc = str(c.get("desc") or "")
        prompt = (f"{head}，{desc}，角色定妆照，正面半身，纯色浅灰背景，"
                  f"写实电影质感，皮肤质感真实，年轻精致，无文字无水印")
        r = agnes_image.run_image(prompt, out_path=f"{workdir}/_charref_{name}.png",
                                  ratio="3:4")
        if r.get("ok") and r.get("image_url"):
            refs[name] = r["image_url"]
            try:
                with open(cache, "w", encoding="utf-8") as f:
                    json.dump({"url": r["image_url"], "path": r.get("path", "")},
                              f, ensure_ascii=False)
            except OSError:
                pass
    return refs


# 图像模型没有跨镜头记忆，同一角色每次都会长成不同的人。
# 把角色表里的外形描述拼进 prompt 做「文字锚点」，是当前成本最低的一致性手段。
_STYLE = "都市职场短剧分镜，写实电影质感，自然光，浅景深，竖屏构图"


_SPEAKER = re.compile(r"^\s*([^：:]{1,8}?)\s*(?:[（(][^）)]{0,20}[）)])?\s*[：:]")


def _on_screen_chars(text: str,
                     characters: Optional[Dict[str, Any]]) -> List[str]:
    """判断画面里真正出场的角色。

    关键：台词里被提到的名字不算出场。
    「陈姐：还不去？周总要的是坑你。」画面上只有陈姐，
    如果把周总的定妆照也丢进 i2i，两张脸会被模型揉成一个人。
    """
    names = [n for n in (characters or {}) if n]
    txt = str(text or "")
    m = _SPEAKER.match(txt)
    if m:
        who = m.group(1).strip()
        for n in names:
            if n in who or (who and who in n):
                return [n]
        return []
    # 叙述句按出现先后排序，先出场的通常是画面主体（参考图取第一个）
    return sorted([n for n in names if n in txt], key=lambda n: txt.find(n))


def _char_anchor(text: str, characters: Optional[Dict[str, Any]]) -> str:
    """从分镜原文里找出场角色，返回其外形描述锚点。"""
    if not characters:
        return ""
    parts = []
    for name, c in characters.items():
        if not name or name not in (text or ""):
            continue
        seg = [f"{name}"]
        age = c.get("age")
        gender = {"female": "女性", "male": "男性"}.get(
            str(c.get("gender") or "").lower(), "")
        if age and gender:
            seg.append(f"{age}岁{gender}")
        elif gender:
            seg.append(gender)
        if c.get("desc"):
            seg.append(str(c["desc"]))
        parts.append("：".join([seg[0], "，".join(seg[1:])]) if len(seg) > 1 else seg[0])
    return "；".join(parts)


def _agnes_image_shot(i: int, shot: Dict[str, Any], workdir: str,
                      est_s: float, clip_path: str, animator,
                      characters: Optional[Dict[str, Any]] = None,
                      char_refs: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """agnes 视频拿不到配额时的降级路径：真图 + 推拉 → 动态分镜。

    比占位测试图案强得多，且时长严格对齐分镜，配音轨能直接对上。
    """
    from .cloud_api import agnes_image
    frame = f"{workdir}/_frame_{i + 1:03d}.png"
    prompt = str(shot.get("prompt") or shot.get("raw") or "").strip()
    # 只传一张参考图，所以必须指明谁是画面主体，否则双人镜头会把两张脸揉到一起
    raw_text = str(shot.get("raw") or prompt)
    _who = _on_screen_chars(raw_text, characters)
    main = _who[0] if _who else ""
    others = _who[1:]
    anchor = _char_anchor(main, characters)
    if others:
        brief = []
        for n in others:
            c = (characters or {}).get(n) or {}
            g = {"female": "女", "male": "男"}.get(
                str(c.get("gender") or "").lower(), "")
            brief.append(f"{n}（{c.get('age') or ''}岁{g}）" if c.get("age")
                         else f"{n}（{g}）")
        anchor = "；".join([x for x in (anchor, "、".join(brief)) if x])
    comp = f"画面主体：{main}，正面清晰呈现" if main else ""
    if others:
        comp += f"；{'、'.join(others)}作为次要人物出现在画面中，不与主体混淆"
    full = "；".join([x for x in (prompt, comp,
                                  anchor and f"角色外观固定：{anchor}",
                                  _STYLE) if x])
    # 画面里出现的角色，用其定妆照做 i2i 参考（最多 3 张），锁定长相
    # 参考图取主体角色：多张不同人物的图会被 i2i 揉成混合脸
    ref_urls = next((char_refs[n] for n in _who
                     if n in (char_refs or {})), None)
    img = agnes_image.run_image(full, out_path=frame, ratio="9:16",
                                ref_image=ref_urls)
    if not img.get("ok") or not img.get("path"):
        return {"ok": False, "path": "", "mock": True, "peak_vram_gb": 0,
                "backend": "agnes_image", "error": img.get("error", "出图失败")}
    motion = animator.pick_motion(str(shot.get("shot_type") or ""), i)
    anim = animator.animate_still(img["path"], clip_path, est_s, motion=motion)
    if not anim.get("ok"):
        return {"ok": False, "path": "", "mock": True, "peak_vram_gb": 0,
                "backend": "agnes_image", "error": anim.get("error", "动态化失败")}
    return {"ok": True, "path": clip_path, "mock": False, "peak_vram_gb": 0,
            "backend": f"cloud_agnes_image({motion})", "image_url": img.get("image_url"),
            "error": ""}


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
    # 有本地模型目录（D:\ComfyUI\...\checkpoints）时注入真 checkpoint 参与实跑
    if runner is None:
        from .comfyui_runner import make_comfyui_runner
        _local_dir = workflow.get("local_models_dir", "") or ""
        _has_local = bool(workflow.get("local_models"))
        runner = make_comfyui_runner(
            mock_fallback=True,
            workdir=workdir,
            local_models_dir=_local_dir if (_local_dir and _local_dir != "local") else "",
        )
        if _has_local or runner.local_models:
            # 把本地索引到的 checkpoint 名写回 workflow.local_models，供 efficiency_planner prefer_local
            if runner.local_models:
                workflow.setdefault("local_models", [
                    sp.get("local_file_name") for sp in runner.local_models.values()
                ])

    def _capability_backend_for(kind: str) -> Dict[str, Any]:
        from .model_gateway import choose_backend
        return choose_backend(kind, profile={}, backends={
            "generic_local": {"kind": "*", "cloud": False, "priority": 20},
            "cloud_video": {"kind": "video", "cloud": True, "priority": 30},
            "cloud_audio": {"kind": "audio", "cloud": True, "priority": 30},
            "mock": {"kind": "*", "cloud": False, "priority": 90},
        })

    def _collect_mode_feedback(mode, overlay, plan, qa_summary, model_id):
        """运行模式数据回流：沉淀为可反哺原 workflow 的迭代资产。"""
        return {
            "schema": "mode_feedback_v1",
            "mode": mode,
            "mode_overlay_applied": bool(overlay),
            "params_used": (overlay.get("params") if overlay else {}) or {},
            "model_id": model_id,
            "qa_pass_rate": qa_summary.get("pass_rate"),
            "qa_failed": qa_summary.get("failed", 0),
            "resource_ok": (plan.get("best") or {}).get("resource_ok"),
            "local_models_dir": plan.get("local_models_dir", ""),
            "hot_update_enabled": plan.get("hot_update_enabled", False),
            "feedback_target": "workflow_gen.mode_overlay",
            "can_feedback_to_original_workflow": True,
        }

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
        _chars = (up.get("script_struct", {}) or {}).get("characters") or {}
        # 取上游分镜提示词 → 效率规划择优 → 执行
        shots = (up.get("storyboard_prompt", {}) or {}).get("shots",
                  (up.get("script_struct", {}) or {}).get("shots", []))
        plan = _efficiency_plan_for_video(up)
        best = plan.get("best") or {}
        chosen_model = best.get("model_id") or "wan13b_gguf_q4_offload_480"
        # 云端 API 优先：有 API Key 时强制使用 cloud_kling（T0/T1 无 GPU 也能出片）
        _cloud_force = workflow.get("cloud_model_override")
        if not _cloud_force and _HAS_CLOUD_API:
            # 白皇 22:05：引擎侧视频优先 agnes 自家模型，flash 默认（免费档）。
            # 不写死 pro——pro 只有调用方显式传 cloud_model_override 才用。
            try:
                if has_key("agnes_video"):
                    _cloud_force = "agnes"
            except Exception:
                pass
        # 注意：密钥名是 agnes_video / agnes_image，"agnes" 只是服务族名，
        # 直接 has_key("agnes") 会查不到 → 默认路径静默回落到本地占位模型。
        _agnes_ok = (_cloud_force in ("agnes", "agnes_video", "agnes_image")
                     and (has_key("agnes_video") or has_key("agnes_image")))
        if _cloud_force and _HAS_CLOUD_API and (_agnes_ok or has_key(_cloud_force)):
            chosen_model = f"cloud_{_cloud_force}"
        # 角色定妆照只出一次，后续所有分镜复用同一批 URL 做 i2i 参考
        _refs = _ensure_char_refs(_chars, workdir) if _chars else {}
        # 视频通道一旦确认不可用（队列满/额度不足），整集直接走分镜图路径。
        # 否则 10 个镜头每个都排队退避，一集要跑一两个小时。
        _video_gave_up = [False]
        executed = []
        qa_decisions = []
        for i, sh in enumerate(shots[:10]):
            # 云端模型分支
            _is_cloud = chosen_model.startswith("cloud_")
            if _is_cloud and _HAS_CLOUD_API:
                _svc = chosen_model.replace("cloud_", "")
                from .cloud_api import wan, kling, seedream
                if _svc in ("agnes", "agnes_video", "agnes_image"):
                    from .cloud_api import agnes_video
                    from . import storyboard_animator as _sa
                    clip_path = f"{workdir}/_clip_{i+1:03d}.mp4"
                    _est = float(sh.get("est_s") or 5.4)
                    cloud_res: Dict[str, Any] = {"ok": False, "error": ""}

                    if _svc != "agnes_image" and not _video_gave_up[0]:
                        cloud_res = agnes_video.run_shot(
                            sh.get("prompt", ""),
                            out_path=clip_path,
                            # flash 是默认免费档；pro 只能由 cloud_model_override 点名
                            model=(agnes_video.MODEL_PRO
                                   if workflow.get("video_model_tier") == "pro"
                                   else agnes_video.MODEL_FLASH),
                            seconds=int(min(12, max(4, round(_est)))),
                            # 只探测性重试：真排不上就整集切图，别让一集等一小时
                            queue_retry=2,
                        )
                        if not cloud_res.get("ok"):
                            _video_gave_up[0] = True

                    if cloud_res.get("ok"):
                        out = {"ok": True,
                               "backend": f"cloud_agnes({cloud_res.get('model','')})",
                               "path": cloud_res.get("path", ""),
                               "video_url": cloud_res.get("video_url"),
                               "mock": False, "peak_vram_gb": 0, "error": ""}
                    else:
                        # 视频配额/队列不可用时降级到「真实分镜图 + 推拉」动态分镜。
                        # 画面仍是 AI 生成的真图，不是占位测试图案，配音照样能对上。
                        _downgrade = _agnes_image_shot(
                            i, sh, workdir, _est, clip_path, _sa,
                            characters=_chars, char_refs=_refs)
                        out = _downgrade
                        if not _downgrade.get("ok"):
                            out = dict(_downgrade)
                            out["video_error"] = cloud_res.get("error", "")
                elif _svc == "kling":
                    cloud_res = kling.run_shot(sh.get("prompt", ""), duration=5)
                    out = {"ok": cloud_res.get("ok"), "backend": chosen_model,
                           "video_url": cloud_res.get("video_url"), "peak_vram_gb": 0}
                elif _svc == "wan":
                    cloud_res = wan.run_shot(sh.get("prompt", ""), resolution="480p")
                    out = {"ok": cloud_res.get("ok"), "backend": chosen_model,
                           "video_url": cloud_res.get("video_url"), "peak_vram_gb": 0}
                elif _svc == "seedream":
                    cloud_res = seedream.run_image(sh.get("prompt", ""))
                    out = {"ok": cloud_res.get("ok"), "backend": chosen_model,
                           "image_url": cloud_res.get("image_url"), "peak_vram_gb": 0}
                else:
                    out = runner.exec(f"shot_{i+1}", model_impl=chosen_model)
            else:
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
                # 关键：保留真实产物路径与 mock 标记，否则下游误判"已生成"
                "path": out.get("path", "") or out.get("image_path", "")
                        or out.get("video_path", ""),
                "mock": bool(out.get("mock")),
                # 分镜时长：合成环节要靠它把片段拉到与配音一致的时长
                "est_s": float(sh.get("est_s") or 5.4),
                "peak_vram": out.get("peak_vram_gb"),
                # 失败原因必须落盘：否则一个镜头变占位就成黑盒，无从排查
                "error": str(out.get("error", "") or out.get("video_error", "") or "")[:300],
                "backend": out.get("backend") or chosen_model,
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
        overlay = workflow.get("mode_overlay") or {}
        raw_mode = str(workflow.get("mode", overlay.get("mode", "beginner"))).lower()
        mode = raw_mode if raw_mode in {"beginner", "pro", "expert"} else "beginner"
        feedback = _collect_mode_feedback(mode, overlay, plan, qa_summary, chosen_model)
        if feedback:
            try:
                from .workflow_gen import apply_mode_feedback
                workflow.clear()
                workflow.update(apply_mode_feedback(workflow, feedback))
            except Exception:
                workflow["mode_feedback"] = feedback
        accessibility = {
            "mode": mode,
            "mode_label": {"beginner": "新手", "pro": "进阶", "expert": "专家"}[mode],
            "params": mode_params(mode, {"tier": workflow.get("tier", "T1")})["params"],
            "cost_panel": cost_visibility(plan),
            "failure_panel": friendly_failure(plan, qa_summary),
            "mode_overlay": workflow.get("mode_overlay") or overlay,
            "mode_feedback": feedback,
        }
        _mock_n = sum(1 for c in executed if c.get("mock"))
        _real_n = sum(1 for c in executed
                      if c.get("path") and not c.get("mock"))
        return {
            "video_clips": executed,
            "clip_count": len(executed),
            "clip_real_count": _real_n,
            "clip_mock_count": _mock_n,
            "video_is_mock": _mock_n > 0 and _real_n == 0,
            "efficiency_best_model": chosen_model,
            "efficiency_plan": plan,
            "qa_loop_summary": qa_summary,
            "accessibility": accessibility,
            "mode_feedback": feedback,
        }

    def _voice_track_exec(up: Dict[str, Any]) -> Dict[str, Any]:
        """真·配音轨：从分镜台词合成，按镜头时间轴对齐。"""
        from .voice_track_builder import build_voice_track
        ss = up.get("script_struct", {}) or {}
        shots = ss.get("shots", [])
        chars = ss.get("characters") or {}
        out = f"{workdir}/voice_ep{ep}.mp3"
        res = build_voice_track(shots, out, workdir=f"{workdir}/_voice",
                                backend=workflow.get("tts_backend", ""),
                                characters=chars)
        return {"voice_track": voice_track,
                "voice_characters": chars,
                "voice_path": res.get("path", ""),
                "voice_ok": bool(res.get("ok")),
                "voice_line_count": res.get("line_count", 0),
                "voice_synthesized": res.get("synthesized", 0),
                "voice_failed": res.get("failed", 0),
                "voice_overflow_lines": res.get("overflow_lines", []),
                "voice_duration_s": res.get("duration_s", 0.0),
                "voice_timeline_s": res.get("timeline_s", 0.0),
                "voice_backend": res.get("backend", ""),
                "voice_error": res.get("error", "")}

    def _music_track_exec(up: Dict[str, Any]) -> Dict[str, Any]:
        """真·音乐轨：从 matrix 风格表构造规格并生成。"""
        from .music_gen import build_music_spec, generate, find_local_asset
        dur = 0.0
        try:
            from .voice_track_builder import total_duration
            dur = total_duration(up.get("script_struct", {}).get("shots", []), 30.0)
        except Exception:
            dur = 30.0
        key = music_track or "M28_anime_jpop"
        spec = build_music_spec(key, duration_s=int(max(10, dur)))
        out_mp3 = f"{workdir}/music_ep{ep}.mp3"
        # 本地素材优先（白皇 2026-10-28：无 SUNO key，素材由平台侧产出落盘）
        src = find_local_asset(workdir, "music", ep, key)
        gen = generate(spec, backend=workflow.get("music_backend", "auto"),
                       out_path=out_mp3, local_src=src)
        return {"music_track": music_track,
                "music_local_src": src,
                "music_pending_asset": not bool(src) and not gen.get("ok"),
                "music_need_api": not bool(src),
                "music_path": gen.get("path", ""),
                "music_ok": bool(gen.get("ok")),
                "music_backend": gen.get("backend", ""),
                "music_duration_ms": gen.get("duration_ms", 0),
                "music_style_zh": spec.get("style_zh", ""),
                "music_style_en": spec.get("style_en", ""),
                "music_spec": spec,
                "music_error": gen.get("error", "")}

    def _bgm_track_exec(up: Dict[str, Any]) -> Dict[str, Any]:
        """真·背景轨：B 类曲目，比音乐轨更低调。"""
        from .music_gen import build_music_spec, generate, find_local_asset
        dur = 0.0
        try:
            from .voice_track_builder import total_duration
            dur = total_duration(up.get("script_struct", {}).get("shots", []), 30.0)
        except Exception:
            dur = 30.0
        key = bgm_track or "B08_suspense_cold"
        spec = build_music_spec(key, duration_s=int(max(10, dur)))
        out_mp3 = f"{workdir}/bgm_ep{ep}.mp3"
        src = find_local_asset(workdir, "bgm", ep, key)
        gen = generate(spec, backend=workflow.get("music_backend", "auto"),
                       out_path=out_mp3, local_src=src)
        return {"bgm_track": key, "bgm_path": gen.get("path", ""),
                "bgm_local_src": src,
                "bgm_pending_asset": not bool(src) and not gen.get("ok"),
                "bgm_need_api": not bool(src),
                "bgm_ok": bool(gen.get("ok")),
                "bgm_backend": gen.get("backend", ""),
                "bgm_duration_ms": gen.get("duration_ms", 0),
                "bgm_style_zh": spec.get("style_zh", ""),
                "bgm_spec": spec, "bgm_error": gen.get("error", "")}

    def _post_assemble(up: Dict[str, Any]) -> Dict[str, Any]:
        # fx_enhance 透传了 fx_clips（源头 video_shot 的 video_clips）
        clips_raw = up.get("fx_enhance", {}).get("fx_clips",
                  up.get("video_shot", {}).get("video_clips", []))
        # video_shot 的 clips 是 [{index,clip,peak_vram}]，取文件路径
        clips_paths = [c.get("path", "") for c in clips_raw if isinstance(c, dict)]
        # 真·ffmpeg 合成：不存在的 clip 自动占位，接 BGM/voice 音频轨
        assembled_path = f"{workdir}/assembled_ep{ep}.mp4"
        from .assembler import assemble as _asm

        # ---- 真·混音：优先用上游真生成的音轨，走 bgm_mix（含对白闪避）----
        import os as _os
        v_up = up.get("voice", {})
        m_up = up.get("music", {})
        b_up = up.get("bgm", {})
        voice_path = v_up.get("voice_path") or ""
        music_path = m_up.get("music_path") or ""
        bgm_path = b_up.get("bgm_path") or ""
        for _k, _p in (("voice", voice_path), ("music", music_path), ("bgm", bgm_path)):
            if _p and not _os.path.exists(_p):
                if _k == "voice":
                    voice_path = ""
                elif _k == "music":
                    music_path = ""
                else:
                    bgm_path = ""

        mix_res: Dict[str, Any] = {}
        _audio = []
        if voice_path or music_path or bgm_path:
            try:
                from .bgm_mix import mix as _mix
                mixed = f"{workdir}/mixed_audio_ep{ep}.mp3"
                mix_res = _mix(voice_path=voice_path or None,
                               bgm_path=bgm_path or None,
                               music_path=music_path or None,
                               out_path=mixed)
                if mix_res.get("ok"):
                    _audio.append(mixed)
            except Exception as _e:  # noqa: BLE001
                mix_res = {"ok": False, "error": f"混音异常: {_e}"}

        # 混音失败/无音轨时退回原始单轨直挂
        if not _audio:
            _audio = [p for p in (voice_path, music_path, bgm_path) if p]

        _durs = [float(c.get("est_s") or 5.4)
                 for c in clips_raw if isinstance(c, dict)] or None
        asm_res = _asm(clips_paths or [""]*max(len(clips_raw),1),
                        audio_tracks=_audio or None,
                        out_path=assembled_path, workdir=workdir,
                        durations=_durs)
        return {"assembled_video": assembled_path,
                "clip_count": asm_res.get("clip_count", len(clips_raw)),
                "music": music_track, "voice": voice_track, "bgm": bgm_track,
                "duration_s": asm_res.get("duration_s", 0),
                "audio_tracks_used": _audio,
                "mix_ok": bool(mix_res.get("ok")),
                "mix_duck_db": mix_res.get("duck_db"),
                "mix_duration_ms": mix_res.get("duration_ms", 0),
                "mix_error": mix_res.get("error", ""),
                "assembled": bool(asm_res.get("ok") or asm_res.get("assembled_video") or assembled_path),
                "assembled_ffmpeg": asm_res.get("ffmpeg", False)}

    def _bgm_audio(up: Dict[str, Any]) -> Dict[str, Any]:
        # 复用 bgm 轨真执行器产出的文件；缺失时给建议 key 但标明未生成
        b = up.get("bgm", {}) or {}
        path = b.get("bgm_path", "")
        import os as _os
        exists = bool(path) and _os.path.exists(path)
        return {"bgm_track": b.get("bgm_track", bgm_track),
                "bgm_path": path,
                "bgm_ok": exists,
                "bgm_backend": b.get("bgm_backend", ""),
                "bgm_style_zh": b.get("bgm_style_zh", ""),
                "note": "" if exists else "BGM 未实际生成（无可用后端），仅给出曲目建议"}

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
        # 叠加音频轨（可选，被裁时不在 dataflow）—— 真执行器
        "music": _music_track_exec,
        "voice": _voice_track_exec,
        "bgm": _bgm_track_exec,
    }
