# -*- coding: utf-8 -*-
"""8 环节全链路 CLI：一条命令 剧本.md + 档位 → 成片。

市场短板补口 C：把 dataflow 拓扑执行接成可执行 CLI，端到端出片。
用法：
  python -m picwf.pipeline_cli --script 剧本.md --tier T1 --style S1_anime_jp \
      --scenario dark_thriller --ep 10 --workdir ./_out
输出：workdir/final_ep10.mp4（成片）+ 各环节产物 + 执行报告 JSON。
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from .workflow_gen import generate_workflow
from .pipeline_runner import run_pipeline_8stage
from .pipeline_executors import make_executors


def _read_script(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run(script_path: str, tier: str = "T1", style: str = "S1_anime_jp",
        scenario: str = "dark_thriller", ep: int = 10,
        free_vram_gb: float = 6.0, audio_mode: str = "auto",
        workdir: str = "./_pipe_cli", resume_ids: List[str] = None,
        mode: str = "beginner",
        auto_repair: bool = True,
        local_models_dir: str = "",
        cloud_model: str = "") -> Dict[str, Any]:
    """一条命令端到端出片：剧本 → 8 环节 → 成片，并透传三档模式。"""
    auto_repair_flag = bool(auto_repair)
    os.makedirs(workdir, exist_ok=True)
    script_text = _read_script(script_path)
    wf = generate_workflow(tier, free_vram_gb=free_vram_gb, style=style,
                           scenario=scenario, ep=ep, audio_mode=audio_mode,
                           mode=mode)
    wf["episode"] = ep
    if local_models_dir:
        wf["local_models_dir"] = local_models_dir
    if cloud_model:
        wf["cloud_model_override"] = cloud_model
    ex = make_executors(wf, workdir=workdir)
    res = run_pipeline_8stage(wf, ex,
                              upstream_inputs={"script_struct": {"text": script_text}},
                              resume_ids=resume_ids)
    # 把模式层结果并入执行报告，供下一轮生成迭代
    mode_feedback = {}
    video_art = res.get("artifacts", {}).get("video_shot", {})
    if isinstance(video_art, dict):
        mode_feedback = video_art.get("mode_feedback", {}) or {}
    # 自动修复：基于交付缺口尝试补产物/重跑/补回流，修复后再体检
    auto_repair_report = {}
    if auto_repair_flag:
        from .auto_repair import repair_delivery, persist_report
        repair = repair_delivery(res, wf, ex, workdir, max_rounds=2)
        auto_repair_report = {
            "ready": repair.get("ready"),
            "rounds": repair.get("rounds"),
            "actions": repair.get("actions"),
            "unresolvable": repair.get("unresolvable"),
            "delivery_readiness": repair.get("delivery_readiness"),
            "local_downgraded": repair.get("local_downgraded", False),
        }
        # 修复后的 artifacts 已写回 res，交付体检以修复后为准
        res["delivery_readiness"] = repair.get("delivery_readiness", _delivery_readiness(res))
        # 学习闭环：ComfyUI 实跑真数据 → matrix.adaptive.yaml，引擎自我迭代
        try:
            from .comfyui_feedback import learn_from_comfyui_runs
            _pkg = os.path.dirname(os.path.abspath(__file__))
            _matrix = os.path.normpath(os.path.join(_pkg, "..", "..", "config", "matrix.yaml"))
            _adapt = os.path.join(workdir, "matrix.adaptive.yaml")
            learn_report = learn_from_comfyui_runs(workdir, _matrix, _adapt)
        except Exception as _e:
            learn_report = {"applied": False, "note": "学习回流未执行: " + type(_e).__name__}
        res["learn_loop"] = learn_report
    else:
        res["delivery_readiness"] = _delivery_readiness(res)

    report_path = os.path.join(workdir, "pipeline_report.json")
    if auto_repair_flag:
        from .auto_repair import persist_report
        # 先合并模式层字段
        res.setdefault("mode", wf.get("mode"))
        res.setdefault("mode_overlay", wf.get("mode_overlay"))
        res.setdefault("mode_feedback", mode_feedback)
        persist_report(res, auto_repair_report, workdir, report_path)
        res["report"] = report_path
        res["final_video"] = res["artifacts"].get("package_publish", {}).get("final_video", "")
        res["auto_repair"] = auto_repair_report
        return res

    report_payload = {"ok": res["ok"], "order": res["order"],
                      "completed": res["completed"], "failed": res["failed"],
                      "artifacts": res["artifacts"],
                      "mode": wf.get("mode"),
                      "mode_overlay": wf.get("mode_overlay"),
                      "mode_feedback": mode_feedback,
                      "delivery_readiness": res["delivery_readiness"]}
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)
    res["report"] = report_path
    res["final_video"] = res["artifacts"].get("package_publish", {}).get("final_video", "")
    res["delivery_readiness"] = res["delivery_readiness"]
    return res


def _delivery_readiness(res: Dict[str, Any]) -> Dict[str, Any]:
    """基于 8 环节执行结果生成可直接交付/缺口的验收结论。"""
    artifacts = res.get("artifacts", {}) or {}
    publish = artifacts.get("package_publish", {}) or {}
    post = artifacts.get("post_assemble", {}) or {}
    video = artifacts.get("video_shot", {}) or {}
    final_video = publish.get("final_video", "")
    has_assembled = bool(post.get("assembled")) and bool(post.get("assembled_video"))
    # ---- 内容真实性判定：区分"能播的预演"和"真正可交付" ----
    # 文件存在不等于内容交付：mock 画面 / 未合成配音 / spec_only 音乐都必须暴露
    real_clips = int(video.get("clip_real_count", 0) or 0)
    mock_clips = int(video.get("clip_mock_count", 0) or 0)
    video_is_mock = bool(video.get("video_is_mock")) or (mock_clips > 0 and real_clips == 0)

    v_art = artifacts.get("voice", {}) or {}
    m_art = artifacts.get("music", {}) or {}
    b_art = artifacts.get("bgm", {}) or {}
    voice_path = v_art.get("voice_path", "") or ""
    music_path = m_art.get("music_path", "") or ""
    bgm_path = b_art.get("bgm_path", "") or ""
    # 只有 dataflow 里存在的环节才要求（安静版可裁掉音频轨）
    wants_voice = bool(v_art)
    wants_music = bool(m_art) or bool(b_art)

    checks = {
        "pipeline_ok": bool(res.get("ok")),
        "publish_ready": bool(publish.get("publish_ready")),
        "final_video_present": bool(final_video and os.path.exists(final_video)),
        "assembled_video_present": bool(has_assembled and os.path.exists(post.get("assembled_video", ""))),
        "video_clips_generated": int(video.get("clip_count", 0) or 0) > 0,
        "qa_loop_visible": "qa_loop_summary" in video,
        "mode_overlay_visible": "mode_overlay" in video,
        "mode_feedback_visible": "mode_feedback" in video,
        # 内容真实性
        "video_clips_real": real_clips > 0,
        "video_is_mock": video_is_mock,
        "voice_track_present": bool(voice_path and os.path.exists(voice_path)),
        "music_track_present": bool(music_path and os.path.exists(music_path)),
        "bgm_track_present": bool(bgm_path and os.path.exists(bgm_path)),
        "audio_mixed": bool(post.get("mix_ok")),
    }
    gaps = []
    if not checks["pipeline_ok"]:
        gaps.append("仍有环节未通过，需先看 failed 清单")
    if not checks["final_video_present"]:
        gaps.append("成片文件尚未落盘，暂不能直接交付")
    if not checks["video_clips_generated"]:
        gaps.append("视频镜头未产生真实产物，只能作为流程预演交付")
    elif video_is_mock:
        gaps.append(
            f"视频画面是占位片（{mock_clips} 个镜头全部 mock，非 AI 生成），"
            "成片只能作为流程预演，不能对外发布")
    elif real_clips < int(video.get("clip_count", 0) or 0):
        gaps.append(f"部分镜头为占位（真实 {real_clips}/{video.get('clip_count')}）")
    if wants_voice and not checks["voice_track_present"]:
        _ve = v_art.get("voice_error") or "TTS 后端不可用"
        gaps.append(
            f"配音轨未生成（解析 {v_art.get('voice_line_count', 0)} 句台词，"
            f"失败 {v_art.get('voice_failed', 0)} 句）：{_ve}")
    if wants_music and not checks["music_track_present"]:
        _mb = m_art.get("music_backend") or b_art.get("bgm_backend") or ""
        gaps.append(
            f"音乐/BGM 未实际生成（当前后端 {_mb or '无'}，仅输出风格规格，"
            "需接音乐生成 API 或人工按 style_zh 制作）")
    if wants_voice and checks["voice_track_present"] and not checks["audio_mixed"]:
        gaps.append("音轨未做混音（缺对白闪避），对白与 BGM 可能互相压制")
    if not checks["mode_feedback_visible"]:
        gaps.append("模式数据回流尚未接入该环节输出")

    # ready = 真正可交付；preview_ready = 流程已跑通可预览
    ready = (checks["final_video_present"] and checks["publish_ready"]
             and checks["video_clips_real"] and not video_is_mock
             and (not wants_voice or checks["voice_track_present"]))
    preview_ready = checks["final_video_present"] and checks["pipeline_ok"]
    return {
        "ready": ready,
        "preview_ready": preview_ready,
        "content_grade": ("deliverable" if ready
                          else "preview" if preview_ready else "incomplete"),
        "checks": checks,
        "gaps": gaps,
        "stats": {"clips_real": real_clips, "clips_mock": mock_clips,
                  "voice_lines": v_art.get("voice_line_count", 0),
                  "voice_synthesized": v_art.get("voice_synthesized", 0)},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="8 环节全链路出片 CLI")
    ap.add_argument("--script", required=True, help="剧本 .md 路径")
    ap.add_argument("--tier", default="T1", help="档位 T0/T1/T2")
    ap.add_argument("--style", default="S1_anime_jp", help="画风轨 key")
    ap.add_argument("--scenario", default="dark_thriller", help="剧种场景")
    ap.add_argument("--ep", type=int, default=10, help="集数（分镜数）")
    ap.add_argument("--free-vram-gb", type=float, default=6.0, help="可用显存 GB")
    ap.add_argument("--audio-mode", default="auto", help="音频裁剪模式")
    ap.add_argument("--workdir", default="./_pipe_cli", help="产物输出目录")
    ap.add_argument("--resume", nargs="*", default=None, help="断点：已完成的环节 id")
    ap.add_argument("--mode", default="beginner", help="运行模式：beginner/pro/expert")
    ap.add_argument("--no-auto-repair", action="store_true",
                    help="关闭缺口自动修复（默认开启）")
    ap.add_argument("--explore", action="store_true",
                    help="run after: print active exploration suggestions (no ComfyUI回灌)")
    ap.add_argument("--explore-run", action="store_true",
                    help="run after: POST探索工作流给ComfyUI + 采metrics + 回流矩阵（完整闭环）")
    ap.add_argument("--comfyui-url", default="http://127.0.0.1:8188",
                    help="ComfyUI服务地址（--explore-run 用）")
    ap.add_argument("--local-models-dir", default="",
                    help="本地模型目录（如 D:\\ComfyUI\\...\\checkpoints），"
                         "有真实 checkpoint 时注入实跑 prompt，可把"
                         "真实产物缺口降级为本地可跑")
    ap.add_argument("--cloud-model", default="",
                    help="强制使用云端模型：wan / kling / seedream，"
                         "需在 config/api_keys.env 配置对应 API Key")
    args = ap.parse_args(argv)
    res = run(args.script, tier=args.tier, style=args.style,
              scenario=args.scenario, ep=args.ep, free_vram_gb=args.free_vram_gb,
              audio_mode=args.audio_mode, workdir=args.workdir,
              resume_ids=args.resume, mode=args.mode,
              auto_repair=not args.no_auto_repair,
              local_models_dir=args.local_models_dir,
              cloud_model=args.cloud_model)
    # 主动探索建议（--explore）
    if args.explore:
        try:
            from .workflow_explorer import explore_full_cycle
            _pkg2 = os.path.dirname(os.path.abspath(__file__))
            _mx2 = os.path.normpath(os.path.join(
                _pkg2, '..', '..', 'config', 'matrix.yaml'))
            _ad2 = os.path.join(args.workdir, 'matrix.adaptive.yaml')
            _ex = explore_full_cycle(args.workdir, _mx2, _ad2, top_k=5)
            res['explore_suggestions'] = _ex.get('exploration', {})
            _wfs = _ex.get('workflows', [])
            print(f'  [explore] next batch: {len(_wfs)} unverified combos:')
            for _w in _wfs[:5]:
                _pi = _w.get('plan_item', {})
                print('    - ' + str(_pi.get('tier','?'))
                      + ' / ' + str(_pi.get('node','?'))
                      + ' / ' + str(_pi.get('impl','?')))
        except Exception as _ex_e:
            res['explore_suggestions'] = {'error': type(_ex_e).__name__}
            print('  [explore] suggestion failed: ' + type(_ex_e).__name__)
    # 完整探索闭环（--explore-run）：POST 工作流 + 采 metrics + 回流矩阵
    if getattr(args, 'explore_run', False):
        try:
            from .workflow_explorer import explore_and_learn
            _pkg3 = os.path.dirname(os.path.abspath(__file__))
            _mx3 = os.path.normpath(os.path.join(
                _pkg3, '..', '..', 'config', 'matrix.yaml'))
            _ad3 = os.path.join(args.workdir, 'matrix.adaptive.yaml')
            _full = explore_and_learn(
                args.workdir, _mx3, _ad3,
                base_url=getattr(args, 'comfyui_url', 'http://127.0.0.1:8188'),
                top_k=5)
            res['explore_full'] = {
                'exploration': _full.get('exploration'),
                'batch_results': _full.get('batch_results'),
                'applied': _full.get('applied'),
                'note': _full.get('note'),
            }
            _br = _full.get('batch_results', [])
            print(f'  [explore-run] 探索{len(_br)}组合，'
                  f'成功{sum(1 for x in _br if x.get("ok"))}，'
                  f'矩阵 applied={_full.get("applied")}')
        except Exception as _er_e:
            res['explore_full'] = {'error': type(_er_e).__name__}
            print('  [explore-run] 闭环失败: ' + type(_er_e).__name__)
    # 打印执行摘要
    print(f"✓ 出片完成: {res['final_video']}")
    print(f"  环节序: {res['order']}")
    print(f"  成功 {len(res['completed'])}/{len(res['order'])}，"
          f"失败 {len(res['failed'])}")
    if res["failed"]:
        print(f"  失败环节: {res['failed']}")
    if "delivery_readiness" in res:
        dr = res["delivery_readiness"]
        grade = dr.get("content_grade", "")
        grade_cn = {"deliverable": "可交付", "preview": "仅预演",
                    "incomplete": "不完整"}.get(grade, grade)
        print(f"  可交付: {'是' if dr['ready'] else '否'}（内容等级: {grade_cn}）")
        st = dr.get("stats") or {}
        if st:
            print(f"  内容统计: 真实镜头 {st.get('clips_real', 0)}/"
                  f"{st.get('clips_real', 0) + st.get('clips_mock', 0)}，"
                  f"台词 {st.get('voice_synthesized', 0)}/{st.get('voice_lines', 0)} 句已配音")
        if dr.get("gaps"):
            print("  缺口:")
            for g in dr["gaps"]:
                print(f"    - {g}")
    if "auto_repair" in res:
        ar = res["auto_repair"]
        print(f"  自动修复: {'达成可交付' if ar.get('ready') else '仍有不可修复项'} "
              f"（动作 {len(ar.get('actions', []))} 个，轮次 {ar.get('rounds')}）")
        for u in ar.get("unresolvable", []):
            print(f"    - 仍需实跑: {u}")
        if ar.get("local_downgraded"):
            print(f"    - 已本地降级: 真实产物缺口转本地 checkpoint 可跑")
    print(f"  报告: {res['report']}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
