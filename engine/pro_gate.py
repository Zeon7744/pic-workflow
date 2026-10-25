import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import billing

"""pic-workflow PRO 门控
免费：1 次/天
Pro：不限 + 角色一致性引擎
"""
import os
import time
import json
import urllib.request

# 用量计数（进程内 dict；生产应落 DB）
_usage = {}  # {tenant_id: {"date": "YYYY-MM-DD", "count": int}}

PLAN_RULES = {
    "free": {"max_runs_per_day": 1, "character_consistency": False, "label": "免费版"},
    "pro":  {"max_runs_per_day": 999999, "character_consistency": True, "label": "专业版 ¥99/月"},
}

# 面包多 Pay收款配置（env 注入，不入库）
MBD_APP_ID = os.environ.get("MBD_APP_ID", "0c59dda8a1bb11f19b9552540025c377")
MBD_API_KEY   = os.environ.get("MBD_API_KEY", "")
MBD_GATEWAY_URL    = os.environ.get("MBD_GATEWAY_URL", "https://mbd.pub/@Zeon7744")


def check(plan: str, tenant_id: str = "") -> dict:
    """检查门控：返回 {"allowed", "reason", "remaining", "character_consistency"}。"""
    rules = PLAN_RULES.get(plan, PLAN_RULES["free"])
    today = time.strftime("%Y-%m-%d")

    if plan == "free":
        usage = _usage.get(tenant_id, {"date": today, "count": 0})
        if usage["date"] != today:
            usage = {"date": today, "count": 0}
        if usage["count"] >= rules["max_runs_per_day"]:
            return {
                "allowed": False,
                "reason": "free_daily_limit_reached (1/天)，升级 Pro 解锁",
                "upgrade_url": "https://mbd.pub/@Zeon7744",
                "remaining": 0,
                "character_consistency": False,
            }
        usage["count"] += 1
        _usage[tenant_id] = usage

    return {
        "allowed": True,
        "remaining": rules["max_runs_per_day"] - usage.get("count", 0) if plan == "free" else -1,
        "character_consistency": rules["character_consistency"],
    }


def create_order(plan: str, tenant_id: str = "") -> dict:
    """创建面包多 Pay订单（仅 Pro 升级时调用）。"""
    if plan != "pro":
        return {"ok": False, "error": f"plan '{plan}' 不需要下单"}
    if not MBD_API_KEY:
        return {"ok": False, "error": "MBD_API_KEY 未配，无法下单", "config_hint": "export MBD_API_KEY=..."}
    payload = {
        "user_id": MBD_APP_ID,
        "price": "99",
        "name": "pic-workflow Pro 专业版月度订阅",
        "token": MBD_API_KEY,
    }
    req = urllib.request.Request(
        f"{MBD_GATEWAY_URL}/payment/create",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return {"ok": result.get("code") == 0, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def gate(plan="free"):
    """PRO 门控：免费 1 次/天，Pro 不限（接 billing.check_access）"""
    return billing.check_access(plan)
