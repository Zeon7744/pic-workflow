#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adaptive 反哺闭环 CLI。

用法：
  python3 adaptive_feedback.py --workdir <dir> [--matrix engine/config/matrix.yaml]
    读 <dir>/metrics_history.jsonl，聚类反哺，生成 matrix.adaptive.yaml，
    并打印"反哺前后 档位推荐对比"。
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf import adaptive

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, help="含 metrics_history.jsonl 的目录")
    ap.add_argument("--matrix", default=os.path.join(
        os.path.dirname(__file__), "..", "config", "matrix.yaml"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "..", "config", "matrix.adaptive.yaml"))
    a = ap.parse_args()
    res = adaptive.run_feedback(a.workdir, a.matrix, a.out)
    print(f"反哺闭环：读 {res['samples_total']} 条实机指标，覆盖 {res['cells']} 个 档×节点×模型 桶")
    print(f"已写出自适应矩阵 -> {res['adaptive_matrix']}")
    print("\n=== 反哺前后 档位推荐对比 ===")
    for x in res["before_after"]:
        mark = "  [亲民化迁移]" if x["migrated"] else "  (保持)"
        print(f"  {x['tier']} {x['node']:14s}  {x['before_primary']}  ->  {x['after_primary']}{mark}  "
              f"(reason={x['reason']}, oom_rate={x['oom_rate']}, est_vram={x['est_vram_after']})")
    # 可选：输出档位保守化偏移
    from picwf.record_metrics import load_history
    off = adaptive.fit_tier_offset(load_history(a.workdir))
    print("\n=== 档位保守化偏移（喂回 tier_scoring）===")
    print(json.dumps(off, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    sys.exit(main())
