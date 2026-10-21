# -*- coding: utf-8 -*-
"""验证 shot_qa --record 能把 4 维分+路由落进 metrics_history（adaptive 输入）。"""
import os, sys, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.shot_qa import assess_and_record
from picwf.record_metrics import load_history

def test_record_writes_history():
    d = tempfile.mkdtemp()
    # 不存在的视频也能跑（降级：4维中性，时长0）—— 验证 record 链路通
    res = assess_and_record("nope.mp4", "一个男人走进房间",
                            expected_duration=5.0, workdir=d, task_id="sX",
                            tier="T1", node_id="video_shot",
                            model_impl="wan13b_gguf_q4_offload_480",
                            quant_dtype="gguf_q4")
    rows = load_history(d)
    assert len(rows) == 1, f"应 1 条, got {len(rows)}"
    r = rows[0]
    assert r["task_id"] == "sX"
    assert r["clip_4d"]["intent"] is not None  # 4维分已落
    print("OK record 链路通:", {k: r[k] for k in ("task_id","tier","model_impl","clip_4d")})

if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"PASS {fn.__name__}")
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
