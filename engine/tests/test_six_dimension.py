# -*- coding: utf-8 -*-
"""0.5.12 六维度扩充测试。

覆盖：资源分配 / 兼容性 / 合法性 / 可用度(SLA) / 智能(LoRA+CLIP桥)。
全部离线可跑（不依赖 torch/网络），签名严格对齐各模块实际接口。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from picwf import resource_allocator as ra
from picwf import compat_layer as cl
from picwf import compliance_checker as cc
from picwf import observability as ob
from picwf import lora_train as lt
from picwf import clip_qa_bridge as cqb


def test_resource_allocator_budget_schedule():
    # 预算内可容纳 T2(vram 峰值 11)，T5(26) 超 16 预算被砍
    plan = ra.budget_plan(
        total_budget={"vram_gb": 16.0, "flop": 999, "minutes": 999},
        tasks=[{"id": "s1", "tier": "T2", "priority": 5, "shots": 6},
               {"id": "s2", "tier": "T5", "priority": 1, "shots": 6}])
    assert "s1" in plan["allocated"] and "s2" in plan["dropped"], "T2 入计划、T5 超预算被砍"
    assert plan["fit"] is False, "有 dropped 时 fit=False"
    # 调度分波
    waves = ra.schedule(concurrency=2, task_budgets=[
        {"id": "a", "tier": "T1"}, {"id": "b", "tier": "T1"},
        {"id": "c", "tier": "T1"}, {"id": "d", "tier": "T1"}])
    assert len(waves) == 2 and len(waves[0]["tasks"]) == 2, "4 任务并发 2 -> 2 波"
    # 配额：95% 未超 100% -> 不熔断(healthy) 但触发降速 action
    q = ra.quota_check({"api_calls_today": 95000, "cost_month": 90.0, "oom_count": 1},
                       {"api_calls_limit": 100000, "cost_limit": 100.0, "oom_limit": 5})
    assert q["healthy"] is True and q["actions"], "95% 未超限但应触发降速"
    # 超限(>100%) -> 熔断
    q2 = ra.quota_check({"api_calls_today": 105000, "cost_month": 90.0, "oom_count": 1},
                        {"api_calls_limit": 100000, "cost_limit": 100.0, "oom_limit": 5})
    assert q2["throttle"] is True and q2["healthy"] is False, "超 100% 应熔断"
    # 自适应重分配：OOM 触发降档
    acts = ra.adaptive_realloc({"tasks": [
        {"id": "s1", "tier": "T5", "oom": True, "vram_need": 26.0, "vram_avail": 12.0}]})
    assert acts["realloc"] and acts["freed_vram"] > 0, "OOM 应触发降档并释放显存"


def test_compat_layer_report_and_degrade():
    env = cl.detect_env()
    rep = cl.compat_report(env, target="web_page")
    assert "incompatible" in rep and "degrade" in rep, "报告含不兼容项+降级项"
    # 缺关键依赖 -> 不兼容
    rep2 = cl.compat_report({"os": env.get("os", ""), "deps": {"torch": False, "ffmpeg": False}},
                            target="web_page")
    assert rep2["incompatible"], "缺 torch/ffmpeg 应进不兼容"
    # 无 torch 必降级 T0
    d = cl.degrade_for_env({"has_torch": False})
    assert d["tier_hint"] == "T0", "无 torch 降到 T0 全 mock"


def test_compliance_checker_aggregate():
    # 无 block：文本无红线、素材授权、角色非真人 -> 可发布
    content = cc.content_check(["主角拔刀对峙"])
    copyright_r = cc.copyright_check([{"path": "bg.mp3", "license": "CC0", "commercial_ok": True}])
    portrait = cc.portrait_check([{"name": "陈锋", "based_on_real_person": False, "fictional": True}])
    platform = cc.platform_redline_check("douyin", "动作冲突")
    c = cc.aggregate_compliance(content, copyright_r, portrait, platform)
    assert c["publishable"] is True and c["block_count"] == 0, f"无 block 应可发布: {c}"
    # 制造 block：真人角色未获肖像授权
    portrait_bad = cc.portrait_check([{"name": "某明星", "based_on_real_person": True, "consent_obtained": False}])
    c2 = cc.aggregate_compliance(content, copyright_r, portrait_bad, platform)
    assert c2["publishable"] is False and c2["block_count"] > 0, "真人肖像未授权应 block"


def test_observability_sla_and_health():
    history = [{"peak_vram_gb": 8.2, "oom_degraded": False},
               {"peak_vram_gb": 11.0, "oom_degraded": True}]
    runs = [{"ok": True, "publish_ready": True, "elapsed_s": 60},
            {"ok": True, "publish_ready": False, "elapsed_s": 90}]
    m = ob.collect_metrics(history, runs)
    assert m["success_rate"] == 1.0 and m["publish_ready_rate"] == 0.5
    assert m["oom_rate"] == 0.5
    h = ob.health_score(m)
    assert 0 <= h["score"] <= 100 and h["light"] in ("green", "yellow", "red")
    good = ob.collect_metrics([], [{"ok": True, "publish_ready": True, "elapsed_s": 60}])
    assert ob.sla_report(good)["all_met"] is True, "健康 run 应达成 SLA"


def test_lora_train_plan_priority():
    chars = [
        {"name": "女主", "role": "女主", "n_samples": 24},
        {"name": "龙套", "role": "龙套", "n_samples": 3},
        {"name": "反派", "role": "反派", "n_samples": 12},
    ]
    plan = lt.lora_train_plan(chars)
    rec = plan["recommend"]
    assert "女主" in rec and "龙套" not in rec, "女主(足素材)应训，龙套(轻)不训"
    p = plan["plans"][0]
    assert p["char"] == "女主", "女主优先级最高"
    assert p["res"] == 768 and p["epoch"] == 12, "素材 24 张应落在 20 档(768p/12ep)"


def test_clip_qa_bridge_degrades_gracefully():
    # 无 torch 时 clip 降级中性，链路仍可跑
    dims = cqb.observe_multimodal("shot.mp4", ["男人拔刀"])
    assert "intent" in dims and "lip" in dims and "rhythm" in dims
    r = cqb.qa_with_observation("shot.mp4", ["男人拔刀"])
    assert 0 <= r["overall"] <= 1 and "clip_used" in r and r["note"], "降级须说明"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(vars(t).items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print("PASS", fn.__name__)
        except Exception:
            failed += 1; print("FAIL", fn.__name__); traceback.print_exc()
    print(f"{len(fns)-failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
