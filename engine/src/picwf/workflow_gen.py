# -*- coding: utf-8 -*-
"""工作流生成器：按档位裁剪 8 环节节点，选模型/参数/量化精度。

读 config/matrix.yaml + 档位 → 输出一份"这台机器能跑通"的工作流 YAML。
YAML 是数据不是代码：同一份生成器，换一份 matrix.yaml 就是换个工作流。
"""
import os
from typing import Any, Dict, List

try:
    import yaml
except Exception:
    yaml = None  # 运行时才需要；缺失时给出提示

MATRIX_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "matrix.yaml")


def _load_yaml(path):
    if yaml is None:
        raise RuntimeError("缺少 PyYAML，请 pip install pyyaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_workflow(tier: str, matrix_path: str = MATRIX_PATH_DEFAULT,
                      free_vram_gb: float = 99.0,
                      style: str = "S1_anime_jp",
                      music: str = "", voice: str = "", bgm: str = "",
                      scenario: str = "", ep: int = 0,
                      audio_mode: str = "auto",
                      mode: str = "beginner") -> Dict[str, Any]:
    """生成指定档位 + 画风的工作流。

    tier: T0/T1/T2（MVP）
    free_vram_gb: 运行时可用显存，用于预筛每节点 fallback 的起始级别。
    style: 画风轨（style_tracks 的 key，默认 S1_anime_jp）。
           角色图/视频节点按画风选模型+LoRA+提示词前缀，档位不变。
    返回结构化 workflow（可序列化为 YAML）。
    """
    matrix = _load_yaml(matrix_path)
    tier_name = tier.upper()
    if tier_name not in matrix.get("tiers", {}):
        raise KeyError(f"未知档位 {tier_name}，可用: {list(matrix['tiers'].keys())}")

    nodes: List[Dict[str, Any]] = []
    for node in matrix["nodes"]:
        chain = node.get("fallback_chain", {}).get(tier_name)
        if chain is None:
            # 该档位此节点无配置，回退 T0 云端链
            chain = node.get("fallback_chain", {}).get("T0", [])
        # 亲民化：低配档把安全档(gguf/offload/cloud)提链首
        chain = _apply_friendly_policy(tier_name, chain, matrix.get("default_policy", {}))
        start_lv = 0
        for i, impl in enumerate(chain):
            need = float(impl.get("estimated_vram_need_gb", 0) or 0)
            if need == 0 or free_vram_gb >= need:
                start_lv = i
                break
            start_lv = i
        primary = chain[start_lv]
        nodes.append({
            "id": node["id"],
            "name": node.get("name", node["id"]),
            "primary": primary,
            "fallback_chain": chain,
            "params": primary.get("params", {}),
        })

    # 画风轨：角色图 / 视频节点按 style 选模型链 + LoRA + 提示词前缀
    style_tracks = matrix.get("style_tracks", {})
    st = style_tracks.get(style)
    if st:
        for nd in nodes:
            if nd["id"] == "character_image":
                imgs = st.get("image_model", [])
                # 画风内按档位降级：低配走链尾(量化/云)，高配走链首
                chain = []
                for impl in imgs:
                    chain.append({
                        "impl": impl,
                        "estimated_vram_need_gb": _style_vram(impl, tier_name),
                        "params": {"style": style, "lora": st.get("lora"),
                                   "prompt_prefix": st.get("prompt_prefix", "")},
                    })
                chain = _tier_filter_chain(tier_name, chain)
                chain = _vram_filter(chain, free_vram_gb, min_vram_need=0)
                nd["fallback_chain"] = chain or nd["fallback_chain"]
                nd["primary"] = chain[0] if chain else nd["primary"]
                nd["params"] = nd["primary"].get("params", {})
                nd["style"] = style
            elif nd["id"] == "video_shot":
                vids = st.get("video_model", [])
                chain = []
                for impl in vids:
                    chain.append({
                        "impl": impl,
                        "estimated_vram_need_gb": _style_vram(impl, tier_name),
                        "params": {"style": style, "lora": st.get("lora"),
                                   "prompt_prefix": st.get("prompt_prefix", "")},
                    })
                if chain:
                    chain = _tier_filter_chain(tier_name, chain)
                    chain = _vram_filter(chain, free_vram_gb, min_vram_need=0)
                    nd["fallback_chain"] = chain or nd["fallback_chain"]
                    nd["primary"] = chain[0] if chain else nd["primary"]
                    nd["params"] = nd["primary"].get("params", {})
                    nd["style"] = style

    # ---- 智能音频轨裁剪（省心省事）+ 四维协同优化（精准命中）----
    from .audio_advisor import advise_tracks
    from .combo_optimizer import optimize
    audio_cfg = matrix.get("scenario_resource_map", {})
    scenario_eff = scenario or (audio_cfg.get("DEFAULT_SCENARIO") if audio_cfg else "light_comedy")
    adv = advise_tracks(scenario_eff, matrix, audio_mode=audio_mode, ep=ep or 1)
    adv_ids = [t["id"] for t in adv]
    # 兼容旧调用：显式传了某轨参数但 adv_ids 没包含时，强制补入（不裁剪用户显式指定的轨）
    for _k in ("music", "voice", "bgm"):
        _v = locals().get(_k, "")
        if _v and _k not in adv_ids:
            adv_ids.append(_k)
    # 四维协同优化（ep 有效时跑）
    opt = {}
    if ep:
        opt = optimize(scenario_eff, ep, matrix)
        # 若用户没显式传 music/voice/bgm，用优化器 best 组合补齐（auto 裁剪时保留）
        if not music and "music" in adv_ids:
            music = opt.get("best", {}).get("music", music)
        if not voice and "voice" in adv_ids:
            voice = opt.get("best", {}).get("voice", voice)
        if not bgm and "bgm" in adv_ids:
            bgm = opt.get("best", {}).get("bgm", bgm)

    # 四维音频轨（音乐 M / 声音 V / BGM B）：按裁剪结果生成 + 冲突检测
    from .conflict_check import check_conflict
    _cw = check_conflict(style, music=music, voice=voice, bgm=bgm)
    _meta_extra = {"conflict_warnings": _cw} if _cw else {}
    _meta_extra["audio_mode"] = audio_mode
    _meta_extra["audio_advised"] = adv_ids
    if opt:
        _meta_extra["combo_best"] = opt.get("best", {})
        _meta_extra["combo_alt"] = opt.get("alt", {})
        _meta_extra["combo_scores"] = opt.get("scores", {})
    if music and "music" in adv_ids:
        nodes.append({"id": "music", "name": "M音乐轨_" + music,
            "primary": {"impl": "music_gen." + music,
                        "params": {"track": music, "tracks": matrix.get("music_tracks", {})}},
            "fallback_chain": [{"impl": "cloud_generate_music"}], "style": style})
    if voice and "voice" in adv_ids:
        nodes.append({"id": "voice", "name": "V声音轨_" + voice,
            "primary": {"impl": "voice_tts." + voice,
                        "params": {"track": voice, "tracks": matrix.get("voice_tracks", {})}},
            "fallback_chain": [{"impl": "cloud_tts"}], "style": style})
    if bgm and "bgm" in adv_ids:
        nodes.append({"id": "bgm", "name": "B背景轨_" + bgm,
            "primary": {"impl": "bgm_mix." + bgm,
                        "params": {"track": bgm, "music_tracks": matrix.get("music_tracks", {}),
                                    "bgm_tracks": matrix.get("bgm_tracks", {})}},
            "fallback_chain": [{"impl": "cloud_bgm"}], "style": style})
    # 8 环节全链路数据流编排（按实际生成节点裁剪）
    dataflow = build_dataflow(nodes)
    _ret = {
        "tier": tier_name,
        "tier_label": matrix["tiers"][tier_name].get("label"),
        "free_vram_gb": free_vram_gb,
        "style": style,
        "style_label": st.get("label") if st else "未指定画风",
        "music": music, "voice": voice, "bgm": bgm,
        "nodes": nodes,
        "dataflow": dataflow,
        "note": "YAML 是数据不是代码；引擎按档位+画风+音频轨裁剪，运行时可再降级",
    }
    _ret.update(_meta_extra)
    _ret["mode"] = _normalize_mode(mode)
    _ret["mode_overlay"] = build_mode_overlay(_ret)
    return _ret






def _style_vram(impl: str, tier: str) -> int:
    """画风内某模型实现的显存估算（按档位粗估，0=云端）。"""
    s = (impl or "").lower()
    if any(k in s for k in ["cloud", "kling", "seedream", "agnes", "video", "api"]):
        return 0
    if "flux" in s:
        return 12 if tier in ("T0", "T1") else 16
    if "sdxl" in s or "ltx" in s:
        return 8
    if "wan13b" in s:
        return 5 if "offload" in s or "q4" in s else 9
    if "sd15" in s:
        return 4
    return 6


def _tier_filter_chain(tier: str, chain: list) -> list:
    """画风轨 model 链按档位过滤：T0 无独显强制云端优先。

    T0（无独显卡）：cloud 类排最前，本地 gguf/offload 放后作兜底，
    本地重模型(SDXL/flux lora)直接排到最后。
    T1/T2：保持画风原序（本地 gguf 首选，省成本）。
    """
    if tier != "T0":
        return chain
    import copy
    c = copy.deepcopy(chain)
    weight = {"cloud": 0, "gguf_offload": 1, "local": 3, "local_heavy": 4}
    stable = sorted(c, key=lambda x: weight.get(_impl_class(x.get("impl")), 9))
    return stable


def _vram_filter(chain: list, free_vram_gb: float,
                  min_vram_need: float) -> list:
    """按 free_vram_gb 过滤画风轨 model 链：

    超出 free_vram_gb 的 impl 自动降到下一档。
    例：1060 free_vram=6GB，画风链 [sdxl_anime_lora(12), sd15_gguf_q4(4), cloud]
    → 降到 [sd15_gguf_q4(4), cloud]，跳过 12GB 的 sdxl。
    """
    import copy
    c = copy.deepcopy(chain)
    kept = []
    for impl in c:
        need = float(impl.get("estimated_vram_need_gb", 0) or 0)
        # 云端/0 显存需求始终保留；超出 free_vram 的本地实现跳过
        if need == 0 or need <= free_vram_gb:
            kept.append(impl)
        # 跳过超出显存需求的本地实现（让下一档量化/offload 顶上）
    return kept or c


def _impl_class(impl: str) -> str:
    """实现归类：cloud / gguf_offload / local_heavy / local。"""
    s = (impl or "").lower()
    if any(k in s for k in ["cloud", "kling", "seedream", "agnes", "grok", "api"]):
        return "cloud"
    if "gguf" in s or "offload" in s:
        return "gguf_offload"
    if "fp16" in s or "full" in s or "lora" in s:
        return "local_heavy"
    return "local"


def _apply_friendly_policy(tier: str, chain: list, policy: dict) -> list:
    """亲民化：低配档(T0/T1)把 gguf_offload/cloud 安全档提到链首。

    高端档(T2+)保持原链（已解锁高清/高量化），不强行降档。
    返回重排后的 chain（copy，不改原对象）。
    """
    import copy
    unlock_at = policy.get("unlock_at_tier", "T2")
    tier_order = ["T0", "T1", "T2", "T3", "T4", "T5"]
    is_low = tier in tier_order[:tier_order.index(unlock_at)] if unlock_at in tier_order else False
    if not is_low:
        return chain
    c = copy.deepcopy(chain)
    if tier == "T0":
        # T0 无独显纯云端：cloud 排最前，本地 gguf/offload 放后作兜底
        # 无独显卡上本地 SDXL/flux 类直接 OOM，必须强制云端优先
        weight = {"cloud": 0, "gguf_offload": 1, "local": 3, "local_heavy": 4}
    else:
        # T1/T2 低配：本地 GGUF Q4+offload 首选（省成本），云端兜底排后
        weight = {"gguf_offload": 0, "cloud": 1, "local_heavy": 3, "local": 2}
    rest = [i for i in c if _impl_class(i.get("impl")) in ("local", "local_heavy")]
    safe = [i for i in c if _impl_class(i.get("impl")) in ("gguf_offload", "cloud")]
    safe.sort(key=lambda x: weight.get(_impl_class(x.get("impl")), 9))
    return safe + rest


# 8 环节全链路节点间数据流依赖（按 matrix 真实节点 ID 定义）
# matrix 8 主链：script_struct→character_image→storyboard_prompt→video_shot
#              →fx_enhance→post_assemble→bgm_audio→package_publish
# 叠加音频轨（可裁剪）：music(M)/voice(V)/bgm(B)，并入 bgm_audio 环节
NODE_DATAFLOW = [
    {"id": "script_struct", "name": "① 剧本结构化", "stage": 1,
     "inputs": ["script_text"], "outputs": ["script_nodes", "shots"], "depends_on": []},
    {"id": "character_image", "name": "② 角色图生成", "stage": 2,
     "inputs": ["shots"], "outputs": ["character_refs"], "depends_on": ["script_struct"]},
    {"id": "storyboard_prompt", "name": "③ 分镜提示词", "stage": 3,
     "inputs": ["shots", "character_refs"], "outputs": ["shot_prompts"],
     "depends_on": ["script_struct", "character_image"]},
    {"id": "video_shot", "name": "④ 视频镜头", "stage": 4,
     "inputs": ["shot_prompts", "character_refs"], "outputs": ["video_clips"],
     "depends_on": ["storyboard_prompt"]},
    {"id": "fx_enhance", "name": "⑤ 特效增强", "stage": 5,
     "inputs": ["video_clips"], "outputs": ["fx_clips"], "depends_on": ["video_shot"]},
    {"id": "post_assemble", "name": "⑥ 后期整合", "stage": 6,
     "inputs": ["fx_clips", "voice_track", "music_track", "bgm_track"],
     "outputs": ["assembled_video"], "depends_on": ["fx_enhance", "music", "voice", "bgm"]},
    {"id": "bgm_audio", "name": "⑦ BGM 音频", "stage": 7,
     "inputs": ["assembled_video"], "outputs": ["bgm_track"],
     "depends_on": ["post_assemble"]},
    {"id": "package_publish", "name": "⑧ 包装发布", "stage": 8,
     "inputs": ["assembled_video", "bgm_track"], "outputs": ["final_video"],
     "depends_on": ["post_assemble", "bgm_audio"]},
    # 叠加音频轨（可被裁剪，裁剪时环节直通）
    {"id": "music", "name": "M音乐轨", "stage": 6,
     "inputs": ["shots"], "outputs": ["music_track"], "depends_on": ["script_struct"],
     "clip": True},
    {"id": "voice", "name": "V声音轨", "stage": 6,
     "inputs": ["shots"], "outputs": ["voice_track"], "depends_on": ["script_struct"],
     "clip": True},
    {"id": "bgm", "name": "B背景轨", "stage": 6,
     "inputs": ["music_track", "shots"], "outputs": ["bgm_track"],
     "depends_on": ["music"], "clip": True},
]


def build_dataflow(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按实际生成的节点裁剪 8 环节全链路数据流。

    8 主链环节始终保留；叠加音频轨(music/voice/bgm)仅在实际生成时纳入。
    depends_on_eff 只保留实际存在（已生成）的上游环节，被裁掉的直通，保证一致。
    """
    present_ids = {nd.get("id") for nd in nodes}
    # 收集本数据流将纳入的环节 ID
    included = []
    for spec in NODE_DATAFLOW:
        if spec.get("clip") and spec["id"] not in present_ids:
            continue
        included.append(spec["id"])
    included_set = set(included)
    flow = []
    for spec in NODE_DATAFLOW:
        if spec.get("clip") and spec["id"] not in present_ids:
            continue
        f = {k: v for k, v in spec.items() if k != "clip"}
        f["depends_on_eff"] = [d for d in spec["depends_on"] if d in included_set]
        flow.append(f)
    return flow


def workflow_to_yaml(workflow: Dict[str, Any]) -> str:
    """序列化为 YAML 文本。"""
    if yaml is None:
        raise RuntimeError("缺少 PyYAML")
    return yaml.safe_dump(workflow, allow_unicode=True, sort_keys=False)


def generate_and_dump(tier: str, out_path: str,
                      matrix_path: str = MATRIX_PATH_DEFAULT,
                      free_vram_gb: float = 99.0,
                      style: str = "S1_anime_jp",
                      music: str = "", voice: str = "", bgm: str = "") -> Dict[str, Any]:
    wf = generate_workflow(tier, matrix_path, free_vram_gb, style)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(workflow_to_yaml(wf))
    return wf



def _normalize_mode(mode: str) -> str:
    m = str(mode or "beginner").lower()
    return m if m in {"beginner", "pro", "expert"} else "beginner"


def build_mode_overlay(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """三档模式叠加层：不改变原 workflow 生成结果，只补充运行默认值与审计字段。"""
    from .accessibility_layer import mode_params

    mode = _normalize_mode(workflow.get("mode", "beginner"))
    ctx = {"tier": workflow.get("tier", "T1")}
    params = mode_params(mode, ctx).get("params", {})
    return {
        "mode": mode,
        "mode_label": {"beginner": "新手", "pro": "进阶", "expert": "专家"}[mode],
        "params": params,
        "legacy_workflow_preserved": True,
        "note": "三档模式是叠加层；原 tier/style/audio/dataflow 生成逻辑保持不变",
    }


def apply_mode_feedback(workflow: Dict[str, Any],
                       feedback: Dict[str, Any]) -> Dict[str, Any]:
    """把运行后沉淀的 mode_feedback 回填回原 workflow，作为下一轮生成依据。"""
    if not feedback:
        workflow = dict(workflow)
        workflow["mode_feedback_applied"] = {"applied": False, "reason": "empty_feedback"}
        return workflow
    out = dict(workflow)
    mode = _normalize_mode(feedback.get("mode", workflow.get("mode", "beginner")))
    out["mode"] = mode
    overlay = dict(out.get("mode_overlay") or {})
    overlay["mode"] = mode
    overlay["mode_label"] = {"beginner": "新手", "pro": "进阶", "expert": "专家"}[mode]
    params = dict(overlay.get("params") or {})
    if feedback.get("params_used"):
        params.update(feedback.get("params_used") or {})
    overlay["params"] = params
    overlay.setdefault("iteration_feedback", [])
    overlay["iteration_feedback"].append({
        "schema": feedback.get("schema", "mode_feedback_v1"),
        "model_id": feedback.get("model_id"),
        "qa_pass_rate": feedback.get("qa_pass_rate"),
        "qa_failed": feedback.get("qa_failed"),
        "local_models_dir": feedback.get("local_models_dir"),
        "hot_update_enabled": bool(feedback.get("hot_update_enabled")),
        "resource_ok": feedback.get("resource_ok"),
        "applied_from": "runtime_mode_feedback",
    })
    overlay["legacy_workflow_preserved"] = True
    out["mode_overlay"] = overlay
    out["mode_feedback_applied"] = {
        "applied": True,
        "mode": mode,
        "source": feedback.get("feedback_target", "workflow_gen.mode_overlay"),
        "legacy_fields_preserved": True,
    }
    return out
