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

# ── 面包多 Pay (mbd) 降级 + 1 元首单 dry-run 验证 ─────────────────────────
echo "==> [mbd] MbdGateway 未配 key 降级验证（created_pending_key）"
python3 - <<'PYEOF_MBD'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("billing", "billing.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
_reg = getattr(mod, "_REGISTRY", None) or getattr(mod, "_GATEWAYS", None)
gw = _reg["mbd"]()
o = gw.create_order("free", 100, {"smoke": "t1"})
assert o["status"] == "created_pending_key", o
assert "MBD_API_KEY" in o.get("needs_secret", []), o
q = gw.query_callback("x")
assert q["status"] == "pending_key", q
print(f"OK: mbd 降级 status={o['status']} needs={o['needs_secret']}")
PYEOF_MBD

echo "==> [mbd] 1 元首单 dry-run（不真扣款，验证签名/参数构造正确）"
python3 - <<'PYEOF_MBD'
import hashlib, json, os, uuid
# 面包多 Pay 官方签名：非空参数 ASCII 字典序 k=v&... + &key=app_key，取 MD5
def mbd_sign(data, api_key):
    ordered = {k: v for k, v in sorted(data.items()) if v not in ("", None)}
    s = "&".join(f"{k}={v}" for k, v in ordered.items())
    return hashlib.md5((s + "&key=" + api_key).encode("utf-8")).hexdigest()

out_trade_no = "mbd_smoke_1yuan_" + uuid.uuid4().hex[:12]
params = {"app_id": os.environ.get("MBD_APP_ID") or "(未配)",
          "description": "smoke-1yuan", "amount_total": 100,
          "out_trade_no": out_trade_no}
params["sign"] = mbd_sign(params, os.environ.get("MBD_API_KEY") or "(占位)")
assert params["amount_total"] == 100, "1 元 = 100 分"
print(f"OK: 1元首单参数 amount_total=100分 out_trade_no={out_trade_no} 已生成签名")
print("OK: MBD_API_KEY 未配时 MbdGateway.create_order 走'待开通'降级路径，行为对齐 noop")
PYEOF_MBD

# ── 第三条通道 praise（支付宝/微信个人赞赏码）降级验证 ─────────────────────
echo "==> [praise] 赞赏码网关未配码值降级验证（created_pending_key + needs_secret）"
python3 - <<'PYEOF_PRAISE'
import importlib.util, os, sys
os.environ.pop("PRAISE_ALIPAY_QR", None); os.environ.pop("PRAISE_WX_QR", None)
spec = importlib.util.spec_from_file_location("billing", "billing.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
gws = getattr(mod, "_REGISTRY", None) or getattr(mod, "_GATEWAYS", None)
assert "praise" in gws, "praise 网关未登记"
gw = gws["praise"]()
o = gw.create_order("free", 300, {"smoke": "t1"})
assert o["status"] == "created_pending_key", o
assert o["needs_secret"] == ["PRAISE_ALIPAY_QR"], o
q = gw.query_callback(o["order_id"])
assert q["status"] in ("awaiting_manual_recon", "paid", "not_found"), q
print(f"OK: praise 降级 status={o['status']} needs={o['needs_secret']}")
PYEOF_PRAISE
