# -*- coding: utf-8 -*-
"""对标市场：HookForge 全开 vs 4 参照物 6 维全赢验证。

固化 build_advisory 的 6 维打分 + win_count=6 全赢 + 暗色惊悚 T1 场景增强。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from picwf import benchmark_advisory as ba


class TestBenchmarkMarket:
    """对标市场 6 维全赢 + 场景增强。"""

    def test_full_open_six_dims_all_win(self):
        """全开（不指定剧种）6 维全赢 win_count=6。"""
        report = ba.build_advisory()
        assert report["win_count"] == 6, f"全开应 6 维全赢，实际 win_count={report['win_count']}"
        assert report["win_rate"] == 1.0, f"win_rate 应 1.0，实际={report['win_rate']}"
        # 每维 HookForge 分必须 > 参照物最高分
        for dim, cell in report["dims"].items():
            assert cell["hook_forge"] > cell["best_ref"], \
                f"{dim} 维 HookForge({cell['hook_forge']}) 应高于参照物({cell['best_ref']})"
            assert cell["lead"] > 0, f"{dim} 维超越幅度应>0，实际={cell['lead']}"

    def test_dark_thriller_scenario_boost(self):
        """暗色惊悚场景下容错/偏移维应明显提升。"""
        base = ba.build_advisory()
        dark = ba.build_advisory(scenario="dark_thriller")
        # 场景增强：暗色惊悚（高 OOM 剧种）应提升容错维
        assert dark["hook_forge"]["容错"] >= base["hook_forge"]["容错"], \
            f"暗色惊悚容错维({dark['hook_forge']['容错']}) 应 ≥ 全开({base['hook_forge']['容错']})"
        # 偏移维（combo 学习针对性）应提升
        assert dark["hook_forge"]["偏移"] >= base["hook_forge"]["偏移"], \
            f"暗色惊悚偏移维({dark['hook_forge']['偏移']}) 应 ≥ 全开({base['hook_forge']['偏移']})"

    def test_fault_tolerance_lead_largest(self):
        """容错维超越幅度应最大（三失败类型路由是核心差异）。"""
        report = ba.build_advisory()
        leads = {dim: cell["lead"] for dim, cell in report["dims"].items()}
        assert leads["容错"] == max(leads.values()), \
            f"容错维超越幅度({leads['容错']}) 应为最大，实际各维={leads}"

    def test_resource_count_snapshot(self):
        """matrix_snapshot 资源数应正确（画风20/音乐30/声音30/BGM50/剧种10/阶段5）。"""
        report = ba.build_advisory()
        snap = report["matrix_snapshot"]
        assert snap["style_tracks"] == 20
        assert snap["music_tracks"] == 30
        assert snap["voice_tracks"] == 30
        assert snap["bgm_tracks"] == 50
        assert snap["scenarios"] == 10
        assert snap["arc_stages"] == 5

    def test_export_yaml(self):
        """对标报告可导出 yaml。"""
        report = ba.build_advisory()
        y = ba.export(report, path="/tmp/picwf_bench_test.yaml", fmt="yaml")
        assert os.path.exists(y), "yaml 导出文件应存在"
