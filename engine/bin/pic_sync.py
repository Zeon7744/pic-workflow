#!/usr/bin/env python3
"""
pic-sync: 云电脑与本地状态对比工具
功能：
  1. 扫描 C 盘和 F 盘的 pic-workflow 仓库
  2. 对比 git log / 测试数量 / matrix 版本
  3. 输出差异报告，标记需审核的操作
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

C_PATH = r"C:\Users\Administrator\pic-push"
F_PATH = r"F:\项目\开发\pic"
GITHUB_REPO = "Zeon7744/pic-workflow"

def run_git(path: str, *args) -> str:
    """执行 git 命令，返回 stdout"""
    git_exe = r"C:\Program Files\Git\cmd\git.exe"
    p = subprocess.run(
        [git_exe, "-C", path] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.stdout.strip()

def scan_repo(path: str) -> dict:
    """扫描仓库/目录状态"""
    result = {
        "path": path,
        "exists": os.path.isdir(path),
    }
    if not result["exists"]:
        return result

    # Git 状态（可能不是 git 仓库）
    try:
        result["head"] = run_git(path, "rev-parse", "HEAD")[:8]
        result["branch"] = run_git(path, "rev-parse", "--abbrev-ref", "HEAD")
        result["log_head"] = run_git(path, "log", "-1", "--format=%h %s")
        result["is_git"] = True
    except:
        result["head"] = ""
        result["branch"] = ""
        result["log_head"] = ""
        result["is_git"] = False

    # 测试文件数
    tests_dir = path + "\\engine\\tests"
    if os.path.isdir(tests_dir):
        result["test_count"] = str(len([f for f in os.listdir(tests_dir) if f.startswith("test_") and f.endswith(".py")]))
    else:
        result["test_count"] = "0"

    # bench.py 基准测试脚本（存在性校验）
    bench_path = path + "\\engine\\bin\\bench.py"
    result["has_bench"] = os.path.isfile(bench_path)

    # 剧本模板目录（数量校验）
    templates_dir = path + "\\engine\\templates"
    if os.path.isdir(templates_dir):
        result["template_count"] = str(len([f for f in os.listdir(templates_dir) if f.endswith(".md")]))
    else:
        result["template_count"] = "0"

    # Matrix 版本
    matrix_path = path + "\\engine\\config\\matrix.yaml"
    if os.path.exists(matrix_path):
        with open(matrix_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("version:"):
                    result["matrix_version"] = line.split(":")[1].strip()
                    break

    return result

def compare(c_state: dict, f_state: dict) -> dict:
    """对比两个状态，返回差异报告"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "diff": {},
        "recommendations": []
    }

    # Git HEAD（F盘是非Git同步副本，不比较）
    if c_state.get("head") and f_state.get("head"):
        if c_state.get("head") != f_state.get("head"):
            report["diff"]["git_head"] = {
                "C": c_state.get("head"),
                "F": f_state.get("head"),
                "status": "MISMATCH"
            }
            report["recommendations"].append("Git HEAD 不一致，建议同步")
    elif f_state.get("is_git") == False:
        # F盘是非Git同步副本，正常情况
        pass
    else:
        report["diff"]["git_head"] = {
            "C": c_state.get("head"),
            "F": f_state.get("head"),
            "status": "CHECK"
        }

    # 测试文件数
    if c_state.get("test_count") != f_state.get("test_count"):
        report["diff"]["test_count"] = {
            "C": c_state.get("test_count"),
            "F": f_state.get("test_count"),
            "status": "MISMATCH"
        }
        report["recommendations"].append("测试文件数不一致，需检查")

    # Matrix 版本
    if c_state.get("matrix_version") != f_state.get("matrix_version"):
        report["diff"]["matrix_version"] = {
            "C": c_state.get("matrix_version"),
            "F": f_state.get("matrix_version"),
            "status": "MISMATCH"
        }
        report["recommendations"].append("Matrix 版本不一致，建议同步")

    # bench.py 存在性对比
    if c_state.get("has_bench") != f_state.get("has_bench"):
        report["diff"]["has_bench"] = {
            "C": c_state.get("has_bench"),
            "F": f_state.get("has_bench"),
            "status": "MISMATCH"
        }
        report["recommendations"].append("bench.py 不一致，建议同步")

    # 模板数量对比
    if c_state.get("template_count") != f_state.get("template_count"):
        report["diff"]["template_count"] = {
            "C": c_state.get("template_count"),
            "F": f_state.get("template_count"),
            "status": "MISMATCH"
        }
        report["recommendations"].append("剧本模板数量不一致，需检查")

    # 无差异
    if not report["diff"]:
        report["status"] = "SYNCED"
    else:
        report["status"] = "DIFFERENT"

    return report

def main():
    print("=" * 60)
    print("pic-sync: 云电脑 vs 本地状态对比")
    print("=" * 60)

    c_state = scan_repo(C_PATH)
    f_state = scan_repo(F_PATH)

    print(f"\n[C 盘] {C_PATH}")
    print(f"  HEAD:    {c_state.get('head', 'N/A')}")
    print(f"  Branch:  {c_state.get('branch', 'N/A')}")
    print(f"  Tests:   {c_state.get('test_count', 'N/A')} files")
    print(f"  Matrix:  {c_state.get('matrix_version', 'N/A')}")
    print(f"  bench:   {'✓' if c_state.get('has_bench') else '✗'}")
    print(f"  模板数:  {c_state.get('template_count', 'N/A')} 个")

    print(f"\n[F 盘] {F_PATH}")
    print(f"  HEAD:    {f_state.get('head', 'N/A')}")
    print(f"  Branch:  {f_state.get('branch', 'N/A')}")
    print(f"  Tests:   {f_state.get('test_count', 'N/A')} files")
    print(f"  Matrix:  {f_state.get('matrix_version', 'N/A')}")
    print(f"  bench:   {'✓' if f_state.get('has_bench') else '✗'}")
    print(f"  模板数:  {f_state.get('template_count', 'N/A')} 个")

    report = compare(c_state, f_state)

    print(f"\n{'=' * 60}")
    print(f"状态: {report['status']}")
    print(f"{'=' * 60}")

    if report["diff"]:
        print("\n差异:")
        for key, val in report["diff"].items():
            print(f"  {key}: C={val['C']} | F={val['F']}")
        print("\n建议操作:")
        for r in report["recommendations"]:
            print(f"  - {r}")
    else:
        print("\n✓ 两站同步，无需操作")

    # 输出 JSON 供程序读取
    print(f"\n---JSON---")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
