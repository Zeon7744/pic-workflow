# -*- coding: utf-8 -*-
"""adaptive 反哺闭环单测。
运行：PYTHONPATH=src python3 tests/test_adaptive.py
"""
import os, sys, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf import adaptive
from picwf.record_metrics import record_step
import glob as _glob
_MATRIX_PATH = _glob.glob(os.path.join(os.path.dirname(__file__), "..", "config", "matrix.yaml"))[0]

def _mk_history(workdir):
    """造一批 T1 视频镜头实机指标：本地 wan1.3b Q4 跑挂(OOM) + 迁云端。"""
    base = [
        # 本地 gguf 实跑：T1 视频镜头 3 次，其中 2 次 OOM，峰值 5.6GB
        dict(task_id="s01", tier="T1", node_id="video_shot",
             model_impl="wan13b_gguf_q4_offload_480", quant_dtype="gguf_q4",
             oom_degraded=False, redo_queued=False, peak_vram_gb=5.2,
             shot_elapsed_s=88.0),
        dict(task_id="s02", tier="T1", node_id="video_shot",
             model_impl="wan13b_gguf_q4_offload_480", quant_dtype="gguf_q4",
             oom_degraded=True, redo_queued=True, peak_vram_gb=5.8,
             shot_elapsed_s=210.0),
        dict(task_id="s03", tier="T1", node_id="video_shot",
             model_impl="wan13b_gguf_q4_offload_480", quant_dtype="gguf_q4",
             oom_degraded=True, redo_queued=True, peak_vram_gb=5.8,
             shot_elapsed_s=195.0),
        # 云端兜底实跑：T1 视频镜头 云端 2 次成功
        dict(task_id="s04", tier="T1", node_id="video_shot",
             model_impl="cloud_kling", quant_dtype="cloud",
             oom_degraded=False, redo_queued=False, peak_vram_gb=0.0,
             shot_elapsed_s=42.0),
        dict(task_id="s05", tier="T1", node_id="video_shot",
             model_impl="cloud_kling", quant_dtype="cloud",
             oom_degraded=False, redo_queued=False, peak_vram_gb=0.0,
             shot_elapsed_s=45.0),
    ]
    for b in base:
        record_step(workdir, b["task_id"], tier=b["tier"], node_id=b["node_id"],
                    model_impl=b["model_impl"], quant_dtype=b["quant_dtype"],
                    oom_degraded=b["oom_degraded"], redo_queued=b["redo_queued"],
                    peak_vram_gb=b["peak_vram_gb"], shot_elapsed_s=b["shot_elapsed_s"])
    return base


def test_history_cluster():
    d = tempfile.mkdtemp()
    base = _mk_history(d)
    rows = __import__("picwf.record_metrics", fromlist=["load_history"]).load_history(d)
    buckets = adaptive.cluster_history(rows)
    assert len(buckets) == 2  # 本地 gguf + 云端 两个桶
    gguf = [b for b in buckets if b.endswith("wan13b_gguf_q4_offload_480")][0]
    adv = adaptive.advise_for_cell(buckets[gguf])
    assert adv["samples"] == 3
    assert adv["oom_rate"] == round(2/3, 3)
    assert adv["recommend_migrate"] is True   # OOM -> 亲民化迁云端
    assert adv["est_vram"] is not None        # 实测峰值*余量
    print("OK cluster/advise:", adv)


def test_apply_matrix_migrate():
    d = tempfile.mkdtemp()
    _mk_history(d)
    rows = __import__("picwf.record_metrics", fromlist=["load_history"]).load_history(d)
    buckets = adaptive.cluster_history(rows)
    advice = {k: adaptive.advise_for_cell(v) for k, v in buckets.items()}
    matrix = adaptive._yaml_load(open(_MATRIX_PATH,
                                      encoding="utf-8").read())
    new = adaptive.apply_advice_to_matrix(matrix, advice)
    # 视频镜头 T1 链首应被提到安全档（cloud/gguf），est_vram 被实测覆盖
    vs = [n for n in new["nodes"] if n["id"] == "video_shot"][0]
    chain = vs["fallback_chain"]["T1"]
    head = chain[0]["impl"]
    # 跑挂(OOM)后，本地 wan gguf 应被降级，云端 kling 顶链首
    assert head == "cloud_kling", f"迁移后链首应为 cloud_kling, got {head}"
    # 跑挂本地应排到链尾
    tail = chain[-1]["impl"]
    assert tail == "wan13b_gguf_q4_offload_480", f"跑挂本地应排尾, got {tail}"
    print("OK apply: T1 video chain =",
          [c["impl"] for c in chain])


def test_before_after():
    d = tempfile.mkdtemp()
    _mk_history(d)
    rows = __import__("picwf.record_metrics", fromlist=["load_history"]).load_history(d)
    buckets = adaptive.cluster_history(rows)
    advice = {k: adaptive.advise_for_cell(v) for k, v in buckets.items()}
    matrix = adaptive._yaml_load(open(_MATRIX_PATH,
                                      encoding="utf-8").read())
    baa = adaptive.tier_recommend_before_after(matrix, advice)
    assert any(x["migrated"] for x in baa), "应至少一个桶被亲民化迁移"
    print("OK before_after:")
    for x in baa:
        if x["migrated"]:
            print("  ", x["tier"], x["node"], x["before_primary"],
                  "->", x["after_primary"], "reason=", x["reason"])


def test_tier_offset():
    d = tempfile.mkdtemp()
    _mk_history(d)
    rows = __import__("picwf.record_metrics", fromlist=["load_history"]).load_history(d)
    off = adaptive.fit_tier_offset(rows)
    # T1 OOM 率 2/5=0.4 >0.4? 相等不算，>=0.2 即 -1
    assert off.get("T1", 0) <= 0, f"T1 应保守化, got {off}"
    print("OK tier_offset:", off)


# 让 adaptive 暴露一个 yaml 读取助手，便于测试
if not hasattr(adaptive, "_yaml_load"):
    import yaml as _y
    def _yaml_load(s):
        return _y.safe_load(s)
    adaptive._yaml_load = _yaml_load


if __name__ == "__main__":
    import traceback
    # 先确保助手存在
    import yaml as _y
    adaptive._yaml_load = lambda s: _y.safe_load(s)
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"PASS {fn.__name__}\n")
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
