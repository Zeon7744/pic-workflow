# -*- coding: utf-8 -*-
"""闭环验证：实机跑数 → 双维 combo 学习 → 失败路由 三链路全通。

对应 1060 T1 实机数据验证的三条闭环：
1. 实机指标采集（record_step 带 scenario + combo 字段）
2. 双维 combo 学习（adaptive.combo_learn 按剧种×档位学 best_combo）
3. 失败路由（downgrade.route_fallback 三失败类型 OOM/超时/质量）

验证点：
- OOM 率随剧种场景单调递增（暗色惊悚 > 男频复仇 > 轻喜剧）
- combo_learn 写回 matrix.emotion_arc_map（combo 字段）
- 三失败类型路由决策互不冲突（OOM 跳级 / 超时留档 / 质量收紧）
- 失败路由语义验证：quality 必须 keep_impl=True
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf import record_metrics as rm
from picwf import adaptive as ad
from picwf import downgrade as dg
import yaml

CFG_DIR = os.path.abspath(os.path.join(HERE, "..", "config"))


def _load_video_node_t1():
    matrix = yaml.safe_load(open(os.path.join(CFG_DIR, "matrix.yaml"), encoding="utf-8"))
    nodes = {n["id"]: n for n in matrix["nodes"]}
    vn = nodes["video_shot"]
    return {
        "id": "video_shot",
        "name": vn["name"],
        "fallback_chain": vn["fallback_chain"]["T1"],
        "current_level": 0,
    }


class TestClosedLoop:
    """闭环验证：实机跑数 → 双维 combo → 失败路由 三链路。"""

    def test_1060_t1_record_step_with_scenario_combo(self):
        """实机指标采集：record_step 带 scenario + combo 字段。"""
        workdir = tempfile.mkdtemp(prefix="picwf_closed_")
        rm.record_step(
            workdir, "shot_1",
            tier="T1", node_id="video_shot",
            model_impl="wan13b_gguf_q4_offload_480",
            quant_dtype="q4", oom_degraded=False, redo_queued=False,
            peak_vram_gb=4.0, shot_elapsed_s=54,
            profile={"cpu": {"model": "i7-8750H", "ghz": 2.2, "cores": 8}},
            scenario="dark_thriller",
            combo={"style": "S8_dark_gothic", "music": "M5_suspense",
                   "voice": "V7_deep_male", "bgm": "B22_dark_ambient"},
        )
        rows = rm.load_history(workdir)
        assert len(rows) == 1
        assert rows[0]["scenario"] == "dark_thriller"
        assert rows[0]["combo"]["style"] == "S8_dark_gothic"
        assert rows[0]["peak_vram_gb"] == 4.0
        assert rows[0]["shot_elapsed_s"] == 54

    def test_combo_learn_oom_rate_monotonic(self):
        """双维 combo 学习：OOM 率随剧种场景单调递增。"""
        workdir = tempfile.mkdtemp(prefix="picwf_combo_")
        sim = {
            "light_comedy":  (False, False, False),
            "male_revenge":  (True, False, False),
            "dark_thriller": (True, True, False),
        }
        for sc, oom_seq in sim.items():
            for i, oom in enumerate(oom_seq):
                rm.record_step(
                    workdir, f"{sc}_shot_{i}",
                    tier="T1", node_id="video_shot",
                    model_impl="wan13b_gguf_q4_offload_480",
                    quant_dtype="q4", oom_degraded=oom, redo_queued=oom,
                    peak_vram_gb=4.0, shot_elapsed_s=54,
                    scenario=sc,
                    combo={"style": "S1", "music": "M1", "voice": "V1", "bgm": "B1"},
                )
        learned = ad.combo_learn(rm.load_history(workdir))
        oom_light = learned["light_comedy::T1"]["oom_rate"]
        oom_male = learned["male_revenge::T1"]["oom_rate"]
        oom_dark = learned["dark_thriller::T1"]["oom_rate"]
        assert oom_dark > oom_male > oom_light, \
            f"OOM 率应单调递增 dark>male>light，实际 {oom_dark}/{oom_male}/{oom_light}"
        assert oom_light == 0.0
        assert 0.3 < oom_male < 0.5
        assert oom_dark > 0.6

    def test_combo_learn_writeback_matrix(self):
        """双维 combo 学习写回 matrix.emotion_arc_map。

        需 ≥MIN_SAMPLES(=2) 条实机样本才触发写回，采 3 条。
        """
        workdir = tempfile.mkdtemp(prefix="picwf_writeback_")
        for i in range(3):
            rm.record_step(
                workdir, f"shot_{i}",
                tier="T1", node_id="video_shot",
                model_impl="wan13b_gguf_q4_offload_480",
                quant_dtype="q4", oom_degraded=False, redo_queued=False,
                peak_vram_gb=4.0, shot_elapsed_s=54,
                scenario="dark_thriller",
                combo={"style": "S8_dark_gothic", "music": "M5_suspense",
                       "voice": "V7_deep_male", "bgm": "B22_dark_ambient"},
            )
        learned = ad.combo_learn(rm.load_history(workdir))
        matrix = yaml.safe_load(open(os.path.join(CFG_DIR, "matrix.yaml"), encoding="utf-8"))
        out = ad.apply_combo_learn_to_matrix(matrix, learned)
        eam = out.get("emotion_arc_map", {})
        assert "dark_thriller__T1" in eam, "应写回 dark_thriller__T1 键"
        tier_node = eam["dark_thriller__T1"]
        # 修复后：新剧种键按 5 act 阶段骨架初始化，每阶段 combo 都填 4 维
        assert len(tier_node) == 5, f"应含 5 act 阶段骨架，实际 {len(tier_node)}"
        for st in ("act1_opening", "act2_setup", "act3_mid", "act4_climax", "act5_ending"):
            assert st in tier_node, f"缺 {st}"
            combo = tier_node[st].get("combo", {})
            assert combo.get("style") == "S8_dark_gothic", f"{st} combo.style 应填"
            assert combo.get("music") == "M5_suspense", f"{st} combo.music 应填"
            assert combo.get("voice") == "V7_deep_male", f"{st} combo.voice 应填"
            assert combo.get("bgm") == "B22_dark_ambient", f"{st} combo.bgm 应填"
        # 验证 default_policy.combo_learn_source 标记来源
        assert out.get("default_policy", {}).get("combo_learn_source") == "adaptive_history"

    def test_failure_route_oom_skip_level(self):
        """失败路由：OOM 应跳一级。"""
        node = _load_video_node_t1()
        r = dg.route_fallback(node, free_vram_gb=6.0, failure="oom")
        assert r["level"] == 1, f"OOM 应跳到 level 1，实际 level={r['level']}"
        assert r["impl_name"] == "cloud_kling", f"OOM 应选 cloud_kling，实际={r['impl_name']}"

    def test_failure_route_timeout_stay_level(self):
        """失败路由：超时应在当前档换更快实现（不跳级）。"""
        node = _load_video_node_t1()
        r = dg.route_fallback(node, free_vram_gb=6.0, failure="timeout")
        assert r["level"] == 0, f"超时应在 level 0 找更快实现，实际 level={r['level']}"
        assert r["adjust"].get("timeout_s") is None, "超时 adjust 应含 timeout_s 键"

    def test_failure_route_quality_keep_impl(self):
        """失败路由：质量应保留当前实现（keep_impl=True），收紧参数。"""
        node = _load_video_node_t1()
        r = dg.route_fallback(node, free_vram_gb=6.0, failure="quality")
        assert r["level"] == 0, f"质量应保留 level 0，实际={r['level']}"
        assert r["adjust"].get("keep_impl") is True, "quality 必须 keep_impl=True"
        assert r["adjust"].get("steps_scale") == 0.8, "quality 应收紧 steps"

    def test_three_failure_routes_distinct(self):
        """三失败类型路由决策互不冲突。"""
        node = _load_video_node_t1()
        o = dg.route_fallback(node, 6.0, failure="oom")
        t = dg.route_fallback(node, 6.0, failure="timeout")
        q = dg.route_fallback(node, 6.0, failure="quality")
        assert o["level"] != t["level"], "OOM 和 超时的 level 不该相同"
        assert q["adjust"].get("keep_impl") is True
        assert o["impl_name"] != q["impl_name"], "OOM 跳级后 impl 应不同于 quality 保留的 impl"

    def test_degrade_plan_by_failure(self):
        """1060 T1 实机部署手册：build_degrade_plan_by_failure 三失败类型预案。"""
        node = _load_video_node_t1()
        plan = dg.build_degrade_plan_by_failure(node)
        fr = plan.get("failure_routes", {})
        assert "oom" in fr and "timeout" in fr and "quality" in fr, \
            "应含 oom/timeout/quality 三失败类型"
