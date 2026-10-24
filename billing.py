"""
pic-workflow 收款层 — 面包多 Pay mbd 网关 + 免费版限次门控

先体验后付费：免费额度拉满吸引使用，深度功能赞赏解锁。
网关（环境变量 pic-workflow_BILLING_GATEWAY=noop|mbd，缺省 mbd，面包多 Pay）：
  - NoopGateway  : MVP 占位，不扣款

所有密钥/赞赏码走环境变量，不落代码。
收款/发布：https://mbd.pub/@Zeon7744
"""
import os
import time
import uuid
import json
import hashlib
import urllib.request

_GW_ENV = "pic-workflow_BILLING_GATEWAY"

# ---------- 付费墙规则（价格锚点对齐各仓 README）----------
PAYWALL_RULES = {
    "free":   {"daily_limit": 1, "label": "免费版"},
    "pro":    {"daily_limit": -1, "label": "Pro ¥99/月"},
    "team":   {"daily_limit": -1, "label": "Team ¥399/月"},
    "enterprise": {"daily_limit": -1, "label": "企业版 定制"},
}

_STATE = {"date": "", "count": 0}


def _today():
    return time.strftime("%Y-%m-%d")


def _bump():
    if _STATE["date"] != _today():
        _STATE["date"] = _today()
        _STATE["count"] = 0
    _STATE["count"] += 1
    return _STATE["count"]


# ---------- 网关 ----------
class NoopGateway:
    name = "noop"

    def create_order(self, plan, amount_cents, meta=None):
        return {"order_id": "noop-" + uuid.uuid4().hex[:12], "status": "noop", "amount_cents": amount_cents}

    def query(self, order_id):
        return {"order_id": order_id, "status": "noop"}


# ─────────────────────────── 面包多 Pay 网关（mbd.pub）───────────────────────────
# 官方文档 https://doc.mbd.pub/ ；费率 2% + 0.1 元/笔（<0.5 元免收），以开通页为准。
# 个人可实名收款；支付宝即时到账（5 分钟内），微信次日自动提现至银行卡。
# 环境变量（不入库）：MBD_APP_ID / MBD_API_KEY / MBD_GATEWAY_URL / MBD_WEBHOOK_URL / MBD_PAY_CHANNEL


def mbd_sign_mbd(data: dict, api_key: str) -> str:
    """面包多 Pay 官方签名：非空参数按 key ASCII 字典序拼 k=v&k=v，再 &key=app_key，取 MD5。"""
    ordered = {k: v for k, v in sorted(data.items()) if v not in ("", None)}
    s = "&".join(f"{k}={v}" for k, v in ordered.items())
    return hashlib.md5((s + "&key=" + api_key).encode("utf-8")).hexdigest()


class MbdGateway:
    """
    面包多 Pay 网关：赞赏码 / 支付宝 H5 / 微信 H5 三种收款模式，均走 newapi.mbd.pub。
    未配 MBD_API_KEY/MBD_APP_ID 时降级（对齐 noop 未配密钥行为，不发起真实请求）。
    """
    name = "mbd"
    DEFAULT_BASE = "https://newapi.mbd.pub/release"

    def __init__(self):
        self.app_id = os.getenv("MBD_APP_ID", "")
        self.api_key = os.getenv("MBD_API_KEY", "")
        self.base = os.getenv("MBD_GATEWAY_URL", self.DEFAULT_BASE)
        self.webhook_url = os.getenv("MBD_WEBHOOK_URL", "")

    def _missing(self):
        return [k for k, v in (("MBD_API_KEY", self.api_key), ("MBD_APP_ID", self.app_id)) if not v]

    def _post(self, path, payload):
        import urllib.request as _ur
        body = dict(payload)
        body["app_id"] = self.app_id
        body["sign"] = mbd_sign_mbd(body, self.api_key)
        req = _ur.Request(f"{self.base}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with _ur.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def create_order(self, tenant_id, amount_cents, product, plan, order_meta=None):
        missing = self._missing()
        if missing:
            return {"order_id": "pending", "status": "created_pending_key",
                    "needs_secret": missing, "amount_cents": amount_cents,
                    "plan": plan, "product": product, "gateway": "mbd",
                    "note": "面包多 Pay 未开通：注册 mbd.pub → 闪电结算 → 控制台取 app_id/app_key → 填 MBD_APP_ID + MBD_API_KEY 即可真下单"}
        out_trade_no = "mbd_" + str(uuid.uuid4())[:16]
        payload = {"description": f"{product}({plan})"[:42],
                   "amount_total": int(amount_cents), "out_trade_no": out_trade_no}
        channel = os.getenv("MBD_PAY_CHANNEL", "alipay")
        path = "/wx/prepay" if channel == "wx_h5" else "/alipay/pay"
        if channel == "wx_h5":
            payload["channel"] = "h5"
        try:
            result = self._post(path, payload)
            if "error" in result:
                return {"order_id": out_trade_no, "status": "gateway_rejected", "error": result["error"], "gateway": "mbd"}
            key = "h5_url" if channel == "wx_h5" else "pay_body"
            return {"order_id": out_trade_no, "status": "created",
                    key: result.get("h5_url" if channel == "wx_h5" else "body", ""), "gateway": "mbd"}
        except Exception as e:
            return {"order_id": out_trade_no, "status": "gateway_error", "error": str(e), "gateway": "mbd"}

    def query_callback(self, order_id):
        missing = self._missing()
        if missing:
            return {"order_id": order_id, "status": "pending_key", "paid": False,
                    "needs_secret": missing, "gateway": "mbd"}
        payload = {"out_trade_no": order_id, "app_id": self.app_id}
        payload["sign"] = mbd_sign_mbd(payload, self.api_key)
        try:
            result = self._post("/search_order", payload)
            if "error" in result:
                return {"order_id": order_id, "status": "query_error", "paid": False, "error": result["error"], "gateway": "mbd"}
            state = str(result.get("state", ""))
            return {"order_id": order_id, "status": state, "paid": state in ("1", "2"),
                    "amount_cents": int(result.get("amount", 0)), "gateway": "mbd"}
        except Exception as e:
            return {"order_id": order_id, "status": "query_failed", "paid": False, "error": str(e), "gateway": "mbd"}

    def verify_callback(self, payload):
        """Webhook（charge_succeeded / complaint）：控制台直连 URL + 本地 out_trade_no 去重。"""
        if not isinstance(payload, dict):
            return False
        data = payload.get("data") or {}
        return payload.get("type") in ("charge_succeeded", "complaint") and bool(data.get("out_trade_no"))

    def refund(self, order_id, amount_cents, reason=""):
        missing = self._missing()
        if missing:
            return {"order_id": order_id, "ok": False, "note": "面包多 Pay 凭据未配",
                    "needs_secret": missing, "gateway": "mbd"}
        payload = {"out_trade_no": order_id, "refund_amount": int(amount_cents or 0), "app_id": self.app_id}
        payload["sign"] = mbd_sign_mbd(payload, self.api_key)
        try:
            result = self._post("/refund", payload)
            ok = "error" not in result
            return {"order_id": order_id, "ok": ok, "refunded_cents": amount_cents if ok else 0, "gateway": "mbd"}
        except Exception as e:
            return {"order_id": order_id, "ok": False, "error": str(e), "gateway": "mbd"}


_GATEWAYS = {"noop": NoopGateway, "mbd": MbdGateway}


def get_gateway():
    name = os.getenv(_GW_ENV, "mbd").lower()
    return _GATEWAYS.get(name, NoopGateway)()


def check_access(plan="free", action="use", tenant_id=""):
    """门控：免费版限次；pro/team/enterprise 不限。返回 {"allowed","reason","upgrade_url"}。"""
    rules = PAYWALL_RULES.get(plan, PAYWALL_RULES["free"])
    limit = rules["daily_limit"]
    if limit < 0:
        return {"allowed": True, "reason": "paid", "plan": plan}
    used = _bump()
    if used > limit:
        return {"allowed": False, "reason": "limit_reached", "upgrade_url": "https://mbd.pub/@Zeon7744", "daily_limit": limit}
    return {"allowed": True, "reason": "free_quota", "plan": plan, "used": used}


def get_pricing():
    return PAYWALL_RULES


def create_order_for_plan(plan="pro"):
    amt = {"free": 0, "pro": 9900, "team": 39900, "enterprise": 0}.get(plan, 9900)
    gw = get_gateway()
    return gw.create_order(plan, amt)
