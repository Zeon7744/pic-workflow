#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流生成器 CLI：按档位生成"这台机器能跑通"的工作流 YAML。"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf import workflow_gen

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=["T0","T1","T2","T3","T4","T5"])
    ap.add_argument("--free-vram", type=float, default=99.0)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    out = a.out or os.path.join(os.path.dirname(__file__), "..", "config",
                                f"workflow_{a.tier}.yaml")
    wf = workflow_gen.generate_and_dump(a.tier, out, free_vram_gb=a.free_vram)
    print(f"生成 {a.tier} 工作流 -> {out}")
    for n in wf["nodes"]:
        print(f"  {n['name']}: 主={n['primary'].get('impl')}  "
              f"降级链 {len(n['fallback_chain'])} 级")
    return 0

if __name__ == "__main__":
    sys.exit(main())
