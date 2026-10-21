# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from picwf.tier_scoring import match_tier

def _prof(vram, ram, arch, fp8):
    return {"gpu": {"vram_gb": vram, "arch": arch, "fp8_support": fp8},
            "ram": {"ram_gb": ram}}

def test_1060_is_t1():
    # 开发机 GTX 1060 6GB Pascal + 32GB 内存 -> 应匹 T1
    p = _prof(6.0, 32.0, "Pascal", False)
    m = match_tier(p)
    assert m["tier"] == "T1", f"1060 应 T1, got {m['tier']} score={m['score']}"

def test_3060_12g_is_t2():
    p = _prof(12.0, 32.0, "Ampere", True)
    m = match_tier(p)
    assert m["tier"] == "T2", f"3060 12G 应 T2, got {m['tier']}"

def test_no_gpu_is_t0():
    p = _prof(0.0, 16.0, "None", False)
    m = match_tier(p)
    assert m["tier"] == "T0", f"无 GPU 应 T0, got {m['tier']}"

def test_4090_clamped_t2_mvp():
    p = _prof(24.0, 64.0, "Ada", True)
    m = match_tier(p)
    # 二期档位被钳到 T2
    assert m["tier"] == "T2" and m["clamped"] is True

if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        try:
            fn(); ok += 1; print(f"PASS {fn.__name__}")
        except Exception:
            print(f"FAIL {fn.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(fns)} passed")
    sys.exit(0 if ok == len(fns) else 1)
