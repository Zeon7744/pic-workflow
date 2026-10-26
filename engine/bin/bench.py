#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench：档位基准测试脚本。

运行所有档位（T0/T1/T2），输出各档位工作流配置摘要 + 显存预估。
用于 CI 验证 + 人工选型参考。

用法：
  python3 bench.py                    # 跑全部档位
  python3 bench.py --tier T1          # 只跑 T1
  python3 bench.py --json             # JSON 输出（stdout）
  python3 bench.py --output out.json  # 写文件
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from picwf import workflow_gen, tier_scoring, hw_probe


TIERS = ["T0", "T1", "T2"]


def run_tier(tier: str, style: str = "S1_anime_jp",
             scenario: str = "dark_thriller", free_vram: float = 99.0) -> dict:
    """跑单档，返回配置摘要。"""
    t0 = time.time()
    wf = workflow_gen.generate_workflow(tier, free_vram_gb=free_vram,
                                         style=style, scenario=scenario)
    elapsed = round(time.time() - t0, 3)

    nodes = wf.get("nodes", [])
    node_info = []
    for n in nodes:
        primary = n.get("primary", {})
        fallbacks = n.get("fallback_chain", [])
        node_info.append({
            "id": n["id"],
            "name": n.get("name", ""),
            "primary_impl": primary.get("impl", "?"),
            "primary_vram": primary.get("estimated_vram_need_gb", 0),
            "fallback_count": len(fallbacks),
            "fallback_impls": [fb.get("impl", "?") for fb in fallbacks],
        })

    return {
        "tier": tier,
        "tier_label": wf.get("tier_label", ""),
        "style": style,
        "style_label": wf.get("style", {}).get("label", style) if isinstance(wf.get("style"), dict) else style,
        "scenario": scenario,
        "elapsed_s": elapsed,
        "node_count": len(nodes),
        "nodes": node_info,
        "note": wf.get("note", ""),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="pic-workflow 档位基准测试")
    ap.add_argument("--tier", choices=TIERS + ["all"], default="all",
                    help="测试档位（默认 all）")
    ap.add_argument("--style", default="S1_anime_jp", help="画风轨 key")
    ap.add_argument("--scenario", default="dark_thriller", help="剧种场景")
    ap.add_argument("--free-vram", type=float, default=99.0, help="可用显存 GB")
    ap.add_argument("--json", action="store_true", help="JSON 输出到 stdout")
    ap.add_argument("--output", default=None, help="输出文件路径")
    args = ap.parse_args(argv)

    tiers = TIERS if args.tier == "all" else [args.tier]
    results = []

    for tier in tiers:
        if not args.json:
            print(f"▶ 跑 {tier} ...", file=sys.stderr, flush=True)
        r = run_tier(tier, args.style, args.scenario, args.free_vram)
        results.append(r)
        if not args.json:
            print(f"  ✓ {r['node_count']} 节点, {r['elapsed_s']}s", file=sys.stderr, flush=True)

    # 硬件探测
    profile = hw_probe.build_profile()
    g = profile.get("gpu", {})
    m = tier_scoring.match_tier(profile)

    report = {
        "hardware": {
            "gpu_name": g.get("name") or g.get("vendor"),
            "vram_gb": g.get("vram_gb", 0),
            "arch": g.get("arch"),
            "fp8_support": g.get("fp8_support"),
            "ram_gb": profile.get("ram", {}).get("ram_gb", 0),
        },
        "tier_match": {
            "tier": m["tier"],
            "score": m["score"]["total"],
            "clamped": m["clamped"],
            "mvp_supported": m["mvp_supported"],
        },
        "results": results,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n=== 硬件环境 ===", file=sys.stderr)
        h = report["hardware"]
        print(f"  GPU: {h['gpu_name']}  VRAM={h['vram_gb']}GB  arch={h['arch']}  fp8={h['fp8_support']}", file=sys.stderr)
        print(f"  RAM: {h['ram_gb']}GB", file=sys.stderr)
        tm = report["tier_match"]
        print(f"\n档位匹配: {tm['tier']}  (score={tm['score']}, mvp={tm['mvp_supported']})", file=sys.stderr)

        print("\n=== 档位配置摘要 ===", file=sys.stderr)
        for r in report["results"]:
            print(f"\n  [{r['tier']}] {r['tier_label']} | {r['style']} | {r['scenario']}", file=sys.stderr)
            print(f"  节点数: {r['node_count']}  生成耗时: {r['elapsed_s']}s", file=sys.stderr)
            for n in r["nodes"]:
                fb_str = " → ".join(n["fallback_impls"])
                print(f"    {n['id']:20s}  主={n['primary_impl']:30s}  vram={n['primary_vram']}GB  降级链=[{fb_str}]", file=sys.stderr)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n报告写入: {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
