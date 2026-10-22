# -*- coding: utf-8 -*-
"""test_benchmark：对标超越三件套单测（离线可跑，不依赖网络）。

覆盖 5 项：
  test_benchmark_6dim        6 维打分全开 > 40
  test_benchmark_win_rate    6 维里至少 4 维超越参照物最高
  test_profiler_cost_saving  比 libtv 省的钱 > 0
  test_profiler_vram_saving  T1 6GB 比海螺 12GB 省 6GB
  test_integration           benchmark_advisory 输出可被 resource_profiler 读走
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from picwf import benchmark_advisory as ba
from picwf import resource_profiler as rp


def test_benchmark_6dim():
    rep = ba.build_advisory()
    assert set(rep["dims"].keys()) == set(ba.SIX_DIMS)
    for dim, v in rep["dims"].items():
        assert v["hook_forge"] > 40, f"{dim} 分过低: {v}"


def test_benchmark_win_rate():
    rep = ba.build_advisory()
    assert rep["win_count"] >= 4, f"win_count={rep['win_count']} < 4: {rep['win_dims']}"
    # 每家参照物单独对标也要赢
    for ref in ba.REFERENCE_BASLINES:
        r = ba.build_advisory(ref=ref)
        assert r["win_count"] >= 4, f"{ref} win_count={r['win_count']}"


def test_profiler_cost_saving():
    prof = rp.profile()
    assert prof["savings"]["save_vs_libtv_yuan"] > 0, prof["savings"]
    # 实机口径（单镜头 40s，一集 6 镜头）
    rows = [{"peak_vram_gb": 5.8, "shot_elapsed_s": 40.0,
             "oom_degraded": False, "redo_queued": False}]
    prof2 = rp.profile(rows, mode="measured")
    assert prof2["savings"]["save_vs_libtv_yuan"] > 0


def test_profiler_vram_saving():
    prof = rp.profile()  # 估算模式：T1 6GB vs 海螺 12GB
    assert prof["hook_forge"]["vram_gb"] == 6.0
    assert prof["savings"]["vram_save_mb_vs_hailuo"] == 6144.0, \
        prof["savings"]  # 12GB - 6GB = 6GB = 6144MB
    assert prof["savings"]["extra_styles_vs_jimeng"] == 12  # 20 - 8 = 12


def test_integration(tmp_path=None):
    # benchmark_advisory 输出 → 写文件 → resource_profiler 读走合并
    rep = ba.build_advisory(scenario="male_revenge")
    prof = rp.profile()
    merged = rp.merge_with_benchmark(rep, prof)
    assert merged["benchmark_6dim"]["win_count"] == rep["win_count"]
    assert 0 <= merged["final_score"] <= 100
    # YAML/JSON 往返：advisory 导出后 profiler 可从文件读走再合并
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".yaml")
    os.close(fd)
    ba.export(rep, p, fmt="yaml")
    with open(p, encoding="utf-8") as f:
        raw = f.read()
    if raw.lstrip().startswith("{"):
        advisory2 = json.loads(raw)
    else:
        advisory2 = __import__("yaml").safe_load(raw)
    prof3 = rp.profile([], mode="estimated")
    merged2 = rp.merge_with_benchmark(advisory2, prof3)
    assert merged2["final_formula"].startswith("0.6*")
    os.unlink(p)
