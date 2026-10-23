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
        workdir: str = "./_pipe_cli", resume_ids: List[str] = None) -> Dict[str, Any]:
    """一条命令端到端出片：剧本 → 8 环节 → 成片。"""
    os.makedirs(workdir, exist_ok=True)
    script_text = _read_script(script_path)
    wf = generate_workflow(tier, free_vram_gb=free_vram_gb, style=style,
                           scenario=scenario, ep=ep, audio_mode=audio_mode)
    wf["episode"] = ep
    ex = make_executors(wf, workdir=workdir)
    res = run_pipeline_8stage(wf, ex,
                              upstream_inputs={"script_struct": {"text": script_text}},
                              resume_ids=resume_ids)
    # 写执行报告
    report_path = os.path.join(workdir, "pipeline_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"ok": res["ok"], "order": res["order"],
                   "completed": res["completed"], "failed": res["failed"],
                   "artifacts": res["artifacts"]}, f, ensure_ascii=False, indent=2)
    res["report"] = report_path
    res["final_video"] = res["artifacts"].get("package_publish", {}).get("final_video", "")
    return res


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
    args = ap.parse_args(argv)
    res = run(args.script, tier=args.tier, style=args.style,
              scenario=args.scenario, ep=args.ep, free_vram_gb=args.free_vram_gb,
              audio_mode=args.audio_mode, workdir=args.workdir,
              resume_ids=args.resume)
    # 打印执行摘要
    print(f"✓ 出片完成: {res['final_video']}")
    print(f"  环节序: {res['order']}")
    print(f"  成功 {len(res['completed'])}/{len(res['order'])}，"
          f"失败 {len(res['failed'])}")
    if res["failed"]:
        print(f"  失败环节: {res['failed']}")
    print(f"  报告: {res['report']}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
