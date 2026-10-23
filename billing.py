"""
pic-workflow 收款层 — 爱发电 afdian 网关 + 免费版限次门控

先体验后付费：免费额度拉满吸引使用，深度功能赞赏解锁。
网关（环境变量 pic-workflow_BILLING_GATEWAY=noop|afdian，缺省 noop）：
  - NoopGateway  : MVP 占位，不扣款
  - AfdianGateway: 爱发电（个人创作者 10 分钟开通，API 查订单 + Webhook，无需备案域名）
所有密钥/赞赏码走环境变量，不落代码。
收款/发布：https://afdian.net/@Zeon7744
"""
import os
import time
import uuid
import json
import hashlib
import urllib.request

_AFDIAN = "Zeon7744"
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


class AfdianGateway:
    """爱发电赞赏/订阅网关：未配密钥时返回占位，不发起真实请求。"""
    name = "afdian"

    def __init__(self):
        self.secret = os.getenv("AFDIAN_SECRET_KEY", "")
        self.user_url = "https://afdian.net/@" + _AFDIAN

    def _sign(self, payload):
        if not self.secret:
            return ""
        base = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256((base + self.secret).encode()).hexdigest()

    def create_order(self, plan, amount_cents, meta=None):
        payload = {"order_no": uuid.uuid4().hex, "amount_cents": amount_cents, "plan": plan, "ts": int(time.time())}
        payload["sign"] = self._sign(payload)
        if not self.secret:
            # 未配密钥：返回赞赏页链接，引导用户手动赞赏（骨架不扣款）
            return {"order_id": payload["order_no"], "status": "pending_manual", "afdian_url": self.user_url, "amount_cents": amount_cents}
        # 已配密钥可对接爱发电开放 API（此处保持骨架，避免真实扣款）
        return {"order_id": payload["order_no"], "status": "created", "amount_cents": amount_cents}

    def query(self, order_id):
        return {"order_id": order_id, "status": "unknown_without_secret"}


_GATEWAYS = {"noop": NoopGateway, "afdian": AfdianGateway}


def get_gateway():
    name = os.getenv(_GW_ENV, "noop").lower()
    return _GATEWAYS.get(name, NoopGateway)()


def check_access(plan="free", action="use", tenant_id=""):
    """门控：免费版限次；pro/team/enterprise 不限。返回 {"allowed","reason","upgrade_url"}。"""
    rules = PAYWALL_RULES.get(plan, PAYWALL_RULES["free"])
    limit = rules["daily_limit"]
    if limit < 0:
        return {"allowed": True, "reason": "paid", "plan": plan}
    used = _bump()
    if used > limit:
        return {"allowed": False, "reason": "limit_reached", "upgrade_url": "https://afdian.net/@" + _AFDIAN, "daily_limit": limit}
    return {"allowed": True, "reason": "free_quota", "plan": plan, "used": used}


def get_pricing():
    return PAYWALL_RULES


def create_order_for_plan(plan="pro"):
    amt = {"free": 0, "pro": 9900, "team": 39900, "enterprise": 0}.get(plan, 9900)
    gw = get_gateway()
    return gw.create_order(plan, amt)
