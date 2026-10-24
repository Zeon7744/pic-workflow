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
        mode: str = "beginner") -> Dict[str, Any]:
    """一条命令端到端出片：剧本 → 8 环节 → 成片，并透传三档模式。"""
    os.makedirs(workdir, exist_ok=True)
    script_text = _read_script(script_path)
    wf = generate_workflow(tier, free_vram_gb=free_vram_gb, style=style,
                           scenario=scenario, ep=ep, audio_mode=audio_mode,
                           mode=mode)
    wf["episode"] = ep
    ex = make_executors(wf, workdir=workdir)
    res = run_pipeline_8stage(wf, ex,
                              upstream_inputs={"script_struct": {"text": script_text}},
                              resume_ids=resume_ids)
    # 把模式层结果并入执行报告，供下一轮生成迭代
    mode_feedback = {}
    video_art = res.get("artifacts", {}).get("video_shot", {})
    if isinstance(video_art, dict):
        mode_feedback = video_art.get("mode_feedback", {}) or {}
    report_payload = {"ok": res["ok"], "order": res["order"],
                      "completed": res["completed"], "failed": res["failed"],
                      "artifacts": res["artifacts"],
                      "mode": wf.get("mode"),
                      "mode_overlay": wf.get("mode_overlay"),
                      "mode_feedback": mode_feedback,
                      "delivery_readiness": _delivery_readiness(res)}
    report_path = os.path.join(workdir, "pipeline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)
    res["report"] = report_path
    res["final_video"] = res["artifacts"].get("package_publish", {}).get("final_video", "")
    res["delivery_readiness"] = report_payload["delivery_readiness"]
    return res


def _delivery_readiness(res: Dict[str, Any]) -> Dict[str, Any]:
    """基于 8 环节执行结果生成可直接交付/缺口的验收结论。"""
    artifacts = res.get("artifacts", {}) or {}
    publish = artifacts.get("package_publish", {}) or {}
    post = artifacts.get("post_assemble", {}) or {}
    video = artifacts.get("video_shot", {}) or {}
    final_video = publish.get("final_video", "")
    has_assembled = bool(post.get("assembled")) and bool(post.get("assembled_video"))
    checks = {
        "pipeline_ok": bool(res.get("ok")),
        "publish_ready": bool(publish.get("publish_ready")),
        "final_video_present": bool(final_video and os.path.exists(final_video)),
        "assembled_video_present": bool(has_assembled and os.path.exists(post.get("assembled_video", ""))),
        "video_clips_generated": int(video.get("clip_count", 0) or 0) > 0,
        "qa_loop_visible": "qa_loop_summary" in video,
        "mode_overlay_visible": "mode_overlay" in video,
        "mode_feedback_visible": "mode_feedback" in video,
    }
    gaps = []
    if not checks["pipeline_ok"]:
        gaps.append("仍有环节未通过，需先看 failed 清单")
    if not checks["final_video_present"]:
        gaps.append("成片文件尚未落盘，暂不能直接交付")
    if not checks["video_clips_generated"]:
        gaps.append("视频镜头未产生真实产物，只能作为流程预演交付")
    if not checks["mode_feedback_visible"]:
        gaps.append("模式数据回流尚未接入该环节输出")
    return {
        "ready": checks["final_video_present"] and checks["publish_ready"],
        "checks": checks,
        "gaps": gaps,
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
    args = ap.parse_args(argv)
    res = run(args.script, tier=args.tier, style=args.style,
              scenario=args.scenario, ep=args.ep, free_vram_gb=args.free_vram_gb,
              audio_mode=args.audio_mode, workdir=args.workdir,
              resume_ids=args.resume, mode=args.mode)
    # 打印执行摘要
    print(f"✓ 出片完成: {res['final_video']}")
    print(f"  环节序: {res['order']}")
    print(f"  成功 {len(res['completed'])}/{len(res['order'])}，"
          f"失败 {len(res['failed'])}")
    if res["failed"]:
        print(f"  失败环节: {res['failed']}")
    if "delivery_readiness" in res:
        dr = res["delivery_readiness"]
        print(f"  可交付: {'是' if dr['ready'] else '否'}")
        if dr.get("gaps"):
            print(f"  缺口: {', '.join(dr['gaps'])}")
    print(f"  报告: {res['report']}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
