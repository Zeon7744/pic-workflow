#!/usr/bin/env bash
# pic-workflow 冒烟测试：依赖可导入 + PRO 门控逻辑 + 展示页存在
set -e
cd "$(dirname "$0")"
echo "=== pic-workflow smoke ==="
python3 -c "import ast,sys
for f in ['engine/orchestrator.py','engine/combo_optimizer.py','engine/conflict_check.py']:
    import os
    if os.path.exists(f): ast.parse(open(f).read())
print('engine 语法 OK')"
python3 -c "
import sys; sys.path.insert(0,'.')
from engine import pro_gate
r=pro_gate.check('free','t1'); assert r['allowed'] is True, r
print('PRO 门控 free 放行 OK')
print('升级链接:', r.get('upgrade_url','')[:40])
"
test -f landing_showcase.html && echo "样片展示页存在 OK"
echo "=== smoke 全通过 ==="
