# -*- coding: utf-8 -*-
"""resource_profiler：资源消耗实测算（"对标超越"三件套之二）。

输入两路：
  A. 实机 record_metrics 采集指标（peak_vram_gb / shot_elapsed_s /
     oom_degraded / redo_queued），来自 state.json / metrics_history.jsonl
  B. 4 参照物公开计费/耗时基线（写死在 REFERENCE_BASLINES，
     与 benchmark_advisory 同源，方便后续实机回填）

输出（每集/每镜头口径，自动算）：
  - 比 libtv 省 X 元     （libtv 0.4 元/秒基准）
  - 比 ComfyUI 快 Y 分钟 （ComfyUI 手动拖节点 30 分钟/集基线）
  - 比即梦多 Z 个画风    （即梦官方 8 画风，HookForge 20 画风）
  - 比海螺省 N MB VRAM  （海螺官方 12GB VRAM，HookForge T1 6GB）
  - 综合性价比分（0-100）：4 项优势加权 + 失败惩罚

数据不足时（缺实机指标）用 HOOKFORGE_T1_BASELINE 估算值出"估算模式"，
并标 estimated=True，离线可跑、不依赖网络。

用法：
  python -m picwf.resource_profiler --state /path/workdir/state.json
  python -m picwf.resource_profiler --mode estimated --format json
"""
import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

# ============================================================================
# 参照物公开基线（写死，实机回填点）
# ============================================================================
LIBTV_COST_PER_S = 0.4          # 元/秒（libtv 计费基准）
COMFYUI_MIN_PER_EP = 30.0      # 分钟/集（手动拖节点基线）
JIMENG_STYLE_COUNT = 8         # 即梦官方画风数
HAIUO_VRAM_GB = 12.0          # 海螺官方推荐 VRAM（GB）

HOOKFORGE_T1_BASELINE = {
    # T1（6-8GB 档）估算口径（无 1060 实测时 fallback）：单镜头 4 秒，一集 6 镜头
    "shot_s": 4.0,
    "shots_per_ep": 6,
    "style_count": 20,
    "vram_gb": 6.0,
}

# 1060 T1 实测基线（record_metrics.yaml 读回，覆盖估算值）
_T1_MEASURED_BASELINE = None

def load_t1_measured_baseline(config_path: Optional[str] = None) -> Dict[str, Any]:
    """从 record_metrics.yaml 读 1060 T1 实测基线（覆盖估算值）。

    返回 {"shot_s", "shots_per_ep", "peak_vram_gb", "source"} 或估算 fallback。
    1060 实测：shot_elapsed=54s / shots_per_ep=10 / peak_vram=4.0GB
    """
    global _T1_MEASURED_BASELINE
    if _T1_MEASURED_BASELINE is not None:
        return _T1_MEASURED_BASELINE
    # 估算 fallback（不递归调自身）
    base = dict(HOOKFORGE_T1_BASELINE)
    base["source"] = "estimated"
    if _T1_MEASURED_BASELINE is None:
        _T1_MEASURED_BASELINE = base
    # 尝试读 record_metrics.yaml
    if yaml is None:
        return base
    if config_path is None:
        # 默认路径：engine/config/record_metrics.yaml
        _here = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.abspath(os.path.join(_here, "..", "..", "config", "record_metrics.yaml"))
    try:
        with open(config_path, encoding="utf-8") as f:
            m = yaml.safe_load(f)
        if m and m.get("tier") == "T1" and "metrics" in m:
            mt = m["metrics"]
            base = {
                "shot_s": float(mt.get("shot_elapsed_s", 4.0)),
                "shots_per_ep": int(mt.get("shots_per_ep", 6)),
                "vram_gb": float(mt.get("peak_vram_gb", 6.0)),
                "style_count": 20,
                "source": f"record_metrics.yaml ({m.get('machine','unknown')})",
            }
            _T1_MEASURED_BASELINE = base
            return base
    except Exception:
        pass
    return base


def load_metrics_from_state(state_path: str) -> List[Dict[str, Any]]:
    """从 workdir/state.json 或 metrics_history.jsonl 读实机指标。"""
    rows: List[Dict[str, Any]] = []
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
        rows.extend(state.get("metrics", {}).values())
    hist = state_path.replace("state.json", "metrics_history.jsonl")
    if os.path.exists(hist):
        with open(hist, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """实机指标聚合：peak_vram 取 max，耗时取 mean，OOM/redo 计数。"""
    vrams = [float(r.get("peak_vram_gb") or 0) for r in rows
             if r.get("peak_vram_gb")]
    elaps = [float(r.get("shot_elapsed_s") or 0) for r in rows
             if r.get("shot_elapsed_s")]
    return {
        "peak_vram_gb": round(max(vrams), 2) if vrams else None,
        "avg_shot_s": round(sum(elaps) / len(elaps), 2) if elaps else None,
        "n_oom": sum(1 for r in rows if r.get("oom_degraded")),
        "n_redo": sum(1 for r in rows if r.get("redo_queued")),
        "n_samples": len(rows),
    }


def profile(metrics_rows: Optional[List[Dict[str, Any]]] = None,
            mode: str = "auto") -> Dict[str, Any]:
    """算资源消耗实测算 + 综合性价比分。

    mode: auto（有 metrics 走实机，没有走估算）/ measured / estimated
    """
    rows = metrics_rows
    estimated = False
    if mode == "estimated" or (mode == "auto" and not rows):
        estimated = True
        agg = None
    else:
        agg = _aggregate(rows or [])

    base = load_t1_measured_baseline()
    hf_vram = None if estimated else (agg["peak_vram_gb"] or base["vram_gb"])
    hf_vram = hf_vram if hf_vram else base["vram_gb"]
    shot_s = (None if estimated else agg["avg_shot_s"]) if agg else None
    shot_s = shot_s if shot_s else base["shot_s"]
    ep_s = shot_s * base["shots_per_ep"]            # 单集总时长（秒）
    ep_min = ep_s / 60.0                             # 单集耗时（分钟）

    # ---- 1) 比 libtv 省 X 元：libtv 按 0.4 元/秒对全片计费，
    #      HookForge 本地出片（T1）边际成本≈0，节省 = libtv 全片计费 - 0
    libtv_cost = round(LIBTV_COST_PER_S * ep_s, 2)
    save_vs_libtv_yuan = libtv_cost                   # 省下的全部计费

    # ---- 2) 比 ComfyUI 快 Y 分钟：30 分钟/集基线 - 实机单集分钟数
    faster_than_comfyui_min = round(COMFYUI_MIN_PER_EP - ep_min, 2)

    # ---- 3) 比即梦多 Z 个画风
    extra_styles_vs_jimeng = base["style_count"] - JIMENG_STYLE_COUNT

    # ---- 4) 比海螺省 N MB VRAM（12GB 基线 vs HookForge T1 6GB）
    vram_save_mb = round((HAIUO_VRAM_GB - hf_vram) * 1024, 0)

    # ---- 综合性价比分（0-100）
    #   成本项 40 / 效率项 30 / 资源项 30，再按 OOM+redo 比例扣分
    cost_part = min(40.0, save_vs_libtv_yuan / 50.0 * 40.0)   # 省50元拿满
    speed_part = min(30.0, max(0.0, faster_than_comfyui_min)
                     / 20.0 * 30.0)                            # 快20分钟拿满
    vram_part = min(30.0, max(0.0, vram_save_mb) / 6144.0 * 30.0)  # 省6GB拿满
    score = round(cost_part + speed_part + vram_part, 1)

    n_oom = (agg or {}).get("n_oom", 0)
    n_redo = (agg or {}).get("n_redo", 0)
    n = (agg or {}).get("n_samples", 0)
    if n:
        fail_ratio = (n_oom + n_redo) / float(n)
        score = round(max(0.0, score * (1.0 - 0.5 * fail_ratio)), 1)

    return {
        "mode": "estimated" if estimated else "measured",
        "estimated": estimated,
        "n_samples": n,
        "n_oom": n_oom,
        "n_redo": n_redo,
        "hook_forge": {
            "vram_gb": hf_vram,
            "shot_s": shot_s,
            "ep_s": ep_s,
            "ep_min": round(ep_min, 2),
            "style_count": base["style_count"],
        },
        "baselines": {
            "libtv_cost_per_s": LIBTV_COST_PER_S,
            "comfyui_min_per_ep": COMFYUI_MIN_PER_EP,
            "jimeng_style_count": JIMENG_STYLE_COUNT,
            "hailuo_vram_gb": HAIUO_VRAM_GB,
        },
        "savings": {
            "save_vs_libtv_yuan": save_vs_libtv_yuan,
            "faster_than_comfyui_min": faster_than_comfyui_min,
            "extra_styles_vs_jimeng": extra_styles_vs_jimeng,
            "vram_save_mb_vs_hailuo": vram_save_mb,
        },
        "score_parts": {
            "cost": round(cost_part, 1),
            "speed": round(speed_part, 1),
            "vram": round(vram_part, 1),
        },
        "cost_performance_score": score,
    }


# ============================================================================
# 集成：吃 benchmark_advisory 的输出（6 维 + 场景），合成最终性价比
# ============================================================================
def merge_with_benchmark(advisory: Dict[str, Any],
                         prof: Dict[str, Any]) -> Dict[str, Any]:
    """把 benchmark_advisory 的 6 维报告接进 profiler 结果（数据通路打通）。

    final_score = 0.6 * 6维均分 + 0.4 * 综合性价比分（0-100）
    """
    dims = advisory.get("dims", {})
    dim_avg = (sum(v["hook_forge"] for v in dims.values())
               / float(max(1, len(dims)))) if dims else 0.0
    cp = prof.get("cost_performance_score", 0.0)
    final = round(0.6 * dim_avg + 0.4 * cp, 1)
    out = dict(prof)
    out["benchmark_6dim"] = {
        "avg": round(dim_avg, 1),
        "win_count": advisory.get("win_count", 0),
        "win_rate": advisory.get("win_rate", 0.0),
        "scenario": advisory.get("scenario", "default"),
    }
    out["final_score"] = final
    out["final_formula"] = "0.6*6dim_avg + 0.4*cost_performance"
    return out


def to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def to_yaml(obj: Any) -> str:
    if yaml is None:
        return to_json(obj)
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False)


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    state_path: Optional[str] = None
    mode = "auto"
    fmt = "yaml"
    out: Optional[str] = None
    advisory_path: Optional[str] = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--state":
            i += 1; state_path = argv[i]
        elif a == "--mode":
            i += 1; mode = argv[i]
        elif a == "--format":
            i += 1; fmt = argv[i]
        elif a == "--out":
            i += 1; out = argv[i]
        elif a == "--advisory":
            i += 1; advisory_path = argv[i]
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"unknown arg: {a}", file=sys.stderr)
            return 2
        i += 1

    rows = load_metrics_from_state(state_path) if state_path else None
    prof = profile(rows, mode=mode)
    blob: Any = prof

    if advisory_path:
        from picwf.benchmark_advisory import build_advisory
        rep = None
        if os.path.exists(advisory_path):
            with open(advisory_path, encoding="utf-8") as f:
                raw = f.read()
            try:
                rep = yaml.safe_load(raw) if yaml else json.loads(raw)
            except Exception:
                rep = json.loads(raw)
        if rep is None:
            rep = build_advisory()
        blob = merge_with_benchmark(rep, prof)

    text = to_yaml(blob)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"written: {out} ({fmt})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
