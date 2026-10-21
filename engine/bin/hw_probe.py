#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""硬件探针 CLI：探测本机硬件并（可选）匹配档位、生成工作流。

用法：
  python3 hw_probe.py                 # 打印硬件概况
  python3 hw_probe.py --json          # 输出 profile JSON
  python3 hw_probe.py --match         # 额外输出档位匹配结果
  python3 hw_probe.py --gen T1        # 匹配档位后生成该档工作流到 config/workflow_T1.yaml
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf import hw_probe, tier_scoring, workflow_gen  # noqa

def main():
    profile = hw_probe.build_profile()
    if "--json" in sys.argv:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    else:
        g = profile["gpu"]
        print("硬件探针结果：")
        print(f"  GPU: {g.get('name') or g.get('vendor')}  VRAM={g.get('vram_gb',0)}GB  "
              f"arch={g.get('arch')}  fp8={g.get('fp8_support')}")
        print(f"  RAM: {profile['ram']['ram_gb']}GB")
        print(f"  存储: 可用 {profile['storage']['free_gb']}GB, NVMe={profile['storage']['is_nvme']}")

    if "--match" in sys.argv or "--gen" in sys.argv:
        m = tier_scoring.match_tier(profile)
        print(f"\n档位匹配: {m['tier']}  (score={m['score']['total']}, "
              f"clamped={m['clamped']}, mvp_supported={m['mvp_supported']})")
        print(f"  显存维={m['score']['vram_score']} 内存维={m['score']['mem_score']} "
              f"架构修正={m['score']['arch_correction']}")
    if "--gen" in sys.argv:
        tier = sys.argv[sys.argv.index("--gen") + 1]
        out = os.path.join(os.path.dirname(__file__), "..", "config",
                           f"workflow_{tier}.yaml")
        wf = workflow_gen.generate_and_dump(tier, out)
        print(f"已生成工作流: {out}  (节点数={len(wf['nodes'])})")
    return 0

if __name__ == "__main__":
    sys.exit(main())
