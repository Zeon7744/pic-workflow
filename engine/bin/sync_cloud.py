#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三路同步脚本：
  1) 剧本/SOP/引擎代码  -> Git 推 GitHub Zeon7744/pic-workflow
  2) 视频/数据 xlsx      -> 网盘直连（此处标记，实际接网盘 CLI/API）
  3) 模型权重 80GB+     -> 本机 NVMe 直存，不上传（只登记清单）

用法：python3 sync_cloud.py [--mode git|cloud|manifest|all]
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GIT_DIRS = ["engine", "00_项目简报", "01_剧本", "03_分镜", "08_SOP与模板"]
CLOUD_DIRS = ["04_视频", "05_成片", "06_音频", "07_特效字幕"]  # 视频/数据走网盘
MANIFEST = "09_部署/models_manifest.json"  # 权重清单

GITIGNORE_BIG = ["04_视频/", "05_成片/", "09_部署/models/", "06_音频/",
                 "07_特效字幕/", "*.mp4", "*.mov", "*.xlsx"]
LFS_TRACK = ["02_图像/*.png", "02_图像/*.jpg", "02_图像/**/*.png"]


def run_git():
    cmds = [
        ["git", "init"],
        ["git", "add", "."],
    ]
    remote = "github.com/Zeon7744/pic-workflow"
    for c in cmds:
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0 and c[1] != "init":
            print(f"[git] warn: {c} -> {r.stderr.strip()[:120]}")
    # 设 remote（若未设）
    subprocess.run(["git", "remote", "add", "origin",
                    f"https://github.com/{remote}"], cwd=ROOT)
    subprocess.run(["git", "remote", "set-url", "origin",
                    f"https://github.com/{remote}"], cwd=ROOT)
    print(f"[git] remote -> https://github.com/{remote}")
    print("[git] 请执行: git commit -m 'init pic-workflow' && git push -u origin main")


def run_cloud():
    """视频/数据 网盘直连（占位）。实际接 百度网盘/阿里云盘/Coze 网盘 CLI。"""
    print("[cloud] 待接网盘 CLI/API，暂只登记:")
    for d in CLOUD_DIRS:
        p = os.path.join(ROOT, d)
        n = sum(1 for _, _, files in os.walk(p) for _ in files) if os.path.exists(p) else 0
        print(f"   - {d}  ({n} 个文件)")


def run_manifest():
    """模型权重 80GB+ 只生成清单，不上传。"""
    mdir = os.path.join(ROOT, "09_部署", "models")
    items = []
    if os.path.exists(mdir):
        for f in os.listdir(mdir):
            fp = os.path.join(mdir, f)
            if os.path.isfile(fp):
                items.append({"file": f, "size_gb": round(os.path.getsize(fp) / 1024 ** 3, 2)})
    with open(os.path.join(ROOT, MANIFEST), "w", encoding="utf-8") as f:
        json_dump(f, {"updated": datetime.now().isoformat(),
                      "note": "模型权重本机 NVMe 直存，不上传",
                      "items": items})
    print(f"[manifest] 写入 {MANIFEST} ({len(items)} 项，本机 NVMe 直存)")


def json_dump(f, obj):
    import json
    json.dump(obj, f, ensure_ascii=False, indent=2)


def write_gitignore():
    p = os.path.join(ROOT, ".gitignore")
    lines = ["# 大文件不进 Git", *GITIGNORE_BIG, "",
             "# Git LFS 追踪角色/场景图", *LFS_TRACK, "",
             "state.json", "kfs/", "*.log"]
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[gitignore] 写入 {p}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="all", choices=["git", "cloud", "manifest", "all"])
    a = ap.parse_args()
    write_gitignore()
    if a.mode in ("git", "all"):
        run_git()
    if a.mode in ("cloud", "all"):
        run_cloud()
    if a.mode in ("manifest", "all"):
        run_manifest()
    return 0


if __name__ == "__main__":
    sys.exit(main())
