#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_inspect: 每日巡检脚本（pic-sync + bench + 测试）

运行在 CodeAct 沙箱或 Calendar 定时触发时调用。
输出巡检报告到 logs/daily/YYYY-MM-DD/ 目录。

用法：
  python3 daily_inspect.py              # 默认跑全部
  python3 daily_inspect.py --only-bench # 只跑 bench
  python3 daily_inspect.py --json       # JSON 输出
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

# ROOT 指向 pic-push 根目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ENGINE_DIR = os.path.join(ROOT, "engine")
SRC = os.path.join(ENGINE_DIR, "src")
PROJECT_DIR = "/Coze/Drive/简化画廊"


def run(cmd, cwd=None, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or ENGINE_DIR)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def run_bench():
    """跑 bench，返回 JSON。"""
    code, out, err = run(
        [sys.executable, "bin/bench.py", "--json"],
        cwd=ENGINE_DIR
    )
    if code == 0:
        try:
            return json.loads(out)
        except Exception:
            return {"error": "bench output not valid JSON", "raw": out[:500]}
    return {"error": f"bench failed: {err[:200]}"}


def run_tests():
    """跑 pytest，返回通过数。"""
    code, out, err = run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=ENGINE_DIR
    )
    combined = out + err
    import re
    m = re.search(r"(\d+) passed.*?(\d+) failed.*?(\d+) skipped", combined)
    if m:
        return {"passed": int(m.group(1)), "failed": int(m.group(2)), "skipped": int(m.group(3))}
    # 尝试其他格式
    m2 = re.search(r"(\d+) passed", combined)
    if m2:
        return {"passed": int(m2.group(1)), "failed": 0, "skipped": 0}
    return {"raw": combined[:300]}


def run_pic_sync():
    """跑 pic_sync，返回状态。"""
    sync_py = os.path.join(PROJECT_DIR, "pic-sync", "pic_sync.py")
    if not os.path.isfile(sync_py):
        return {"status": "SKIP", "reason": "pic_sync.py not found"}
    code, out, err = run([sys.executable, sync_py], timeout=30)
    for line in out.split("\n"):
        if line.startswith("---JSON---"):
            try:
                return json.loads(line[11:])
            except Exception:
                pass
    return {"status": "UNKNOWN", "raw": out[:200]}


def run_git_log():
    """获取最新提交。"""
    code, out, err = run(["git", "log", "-1", "--oneline"], cwd=ROOT)
    return out if code == 0 else "N/A"


def main():
    only_bench = "--only-bench" in sys.argv
    json_out = "--json" in sys.argv

    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    log_dir = os.path.join(ENGINE_DIR, "logs", "daily", date_str)
    os.makedirs(log_dir, exist_ok=True)

    report = {
        "ts": ts,
        "date": date_str,
        "git_head": run_git_log(),
    }

    if only_bench:
        report["bench"] = run_bench()
    else:
        t0 = time.time()
        report["bench"] = run_bench()
        report["tests"] = run_tests()
        report["pic_sync"] = run_pic_sync()
        report["elapsed_s"] = round(time.time() - t0, 2)

    report_path = os.path.join(log_dir, f"inspect_{date_str}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if json_out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"=== 每日巡检 {date_str} ===")
        print(f"Git HEAD: {report['git_head']}")
        if "bench" in report:
            b = report["bench"]
            if "hardware" in b:
                h = b["hardware"]
                print(f"Bench: GPU={h['gpu_name']} VRAM={h['vram_gb']}GB RAM={h['ram_gb']}GB")
                for r in b.get("results", []):
                    print(f"  [{r['tier']}] {r['node_count']}节点 {r['elapsed_s']}s")
            elif "error" in b:
                print(f"Bench: ERROR - {b['error']}")
        if "tests" in report:
            t = report["tests"]
            if "passed" in t:
                print(f"Tests: {t['passed']}P / {t.get('failed',0)}F / {t.get('skipped',0)}S")
            else:
                print(f"Tests: {str(t)[:100]}")
        if "pic_sync" in report:
            ps = report["pic_sync"]
            print(f"Pic-sync: {ps.get('status', '?')}")
        print(f"耗时: {report.get('elapsed_s', '?')}s")
        print(f"报告: {report_path}")

    if "tests" in report:
        t = report["tests"]
        if isinstance(t, dict) and t.get("failed", 0) > 0:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
