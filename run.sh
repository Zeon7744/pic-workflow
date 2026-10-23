#!/usr/bin/env bash
# pic-workflow 一键启动
set -euo pipefail
cd "$(dirname "$0")/engine"
pip install -r requirements.txt 2>/dev/null || true
python3 -m pic_workflow --input "02_图像/sample.png" --output "out/" 2>/dev/null || echo "(无 sample.png 时仅验证可启动)"
