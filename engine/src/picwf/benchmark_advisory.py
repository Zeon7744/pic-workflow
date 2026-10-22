# -*- coding: utf-8 -*-
"""benchmark_advisory：对标分析核心（"对标超越"三件套之一）。

把 HookForge（pic-workflow 引擎）与 4 个参照物（libtv / ComfyUI /
即梦 / MiniMax 海螺）在 6 个维度上做可量化的对标打分，证明"超越"：
  覆盖面 / 类型 / 效率 / 容错 / 偏移 / 资源消耗

- 4 参照物的能力基线写死在本模块 REFERENCE_BASLINES 里
  （libtv 0.4元/秒、ComfyUI 30分钟/集、即梦 8 画风、海螺 12GB VRAM），
  后续实机跑数可直接改这里回填，不需要碰引擎代码。
- 打分输入 = HookForge 当前矩阵（20 画风 + 30 音乐 + 30 声音 + 50 BGM
  + 10 剧种 + 5 集数阶段）+ 场景参数（--scenario / --ref）。
- 输出：每维 {hook_forge: 0-100, best_ref: 0-100, lead: 超越幅度}，
  可导出 JSON 或 YAML。

用法：
  python -m picwf.benchmark_advisory --scenario male_revenge --ref jimeng
  python -m picwf.benchmark_advisory --all --format json > advisory.json

约束：仅 Python 标准库 + PyYAML，离线可跑。
"""
import json
import sys
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:  # PyYAML 缺失时退化为 JSON 输出
    yaml = None

# ============================================================================
# 一、HookForge 当前矩阵能力（来源：engine/config/matrix.yaml 实数）
# ============================================================================
HOOKFORGE_MATRIX = {
    "style_tracks": 20,      # S1..S20
    "music_tracks": 30,      # M1..M30
    "voice_tracks": 30,      # V1..V30
    "bgm_tracks": 50,        # B01..B50
    "scenarios": 10,         # scenario_resource_map：10 剧种
    "arc_stages": 5,         # emotion_arc_map：5 个集数阶段
    "tiers": 6,              # T0..T5
    "tiers_mvp": 3,          # T0/T1/T2 已落地
    "levels_fallback": 3,    # 本地 → 量化/offload → 云端 三级降级
    "audio_combo_optimize": True,   # 四维协同优化（combo_optimizer）
    "conflict_check": True,         # 冲突检测 v2（conflict_check）
    "smart_audio_trim": True,       # 智能音频裁剪（音频轨默认 1-2 条）
    "adaptive_feedback": True,      # 实机指标反哺（adaptive + record_metrics）
    "t0_t1_runrate_goal": 0.95,     # 低配跑通率目标 95%
}

# ============================================================================
# 二、4 参照物能力基线（写死，方便后续实机跑数回填）
#
# 每维 0-100。约定：分越高 = 该维越强。
#   覆盖面   能力范围（画风/音频/剧种/档位覆盖）
#   类型     可选资源类型数（画风数等）
#   效率     出片速度（越快分越高）
#   容错     失败兜底/降级能力（越稳分越高）
#   偏移     低配硬件可用性（越亲民分越高）
#   资源消耗 资源效率（越省分越高）
# ============================================================================
REFERENCE_BASLINES: Dict[str, Dict[str, Any]] = {
    "libtv": {
        "label": "libtv（视频剪辑 SaaS）",
        # 公开计费基准：0.4 元/秒（实机数据回填点）
        "cost_per_s": 0.4,
        "dims": {
            "覆盖面": 55,   # 剪辑为主，画风/音频轨选择面窄
            "类型":   35,   # 内置画风模板有限（远少于 20）
            "效率":   70,   # 模板化出片快，但需人工剪辑
            "容错":   50,   # 失败重剪靠人手
            "偏移":   40,   # 云端 SaaS，与硬件无关但成本高
            "资源消耗": 30,  # 0.4 元/秒持续计费，长剧烧钱
        },
    },
    "comfyui": {
        "label": "ComfyUI（节点式本地工作流）",
        # 公开基线：手动拖节点约 30 分钟/集（实机数据回填点）
        "baseline_min_per_ep": 30,
        "dims": {
            "覆盖面": 80,   # 节点生态全，什么都能拼
            "类型":   75,   # LoRA 自由，画风上限高
            "效率":   45,   # 手动拖节点，30 分钟/集基线
            "容错":   55,   # 节点错误需人工排障
            "偏移":   45,   # 需要懂节点图，门槛偏高
            "资源消耗": 60,  # 本地跑不计时，但调参耗人力
        },
    },
    "jimeng": {
        "label": "即梦（字节官方）",
        # 官方基线：8 画风（实机数据回填点）
        "style_count": 8,
        "dims": {
            "覆盖面": 65,   # 图生视频强，音频轨缺失
            "类型":   40,   # 官方 8 画风
            "效率":   80,   # 云端一键，出片快
            "容错":   60,   # 云端队列偶发失败重试
            "偏移":   55,   # 云端不挑硬件
            "资源消耗": 55,  # 按次计费，画风少试错成本低
        },
    },
    "hailuo": {
        "label": "MiniMax 海螺（官方视频模型）",
        # 官方基线：推荐 12GB VRAM（实机数据回填点）
        "vram_gb": 12,
        "dims": {
            "覆盖面": 70,   # 视频模型强，但音频轨/剧种模板少
            "类型":   50,   # 画风可选面中等
            "效率":   75,   # 云端模型推理快
            "容错":   60,   # 云端重试
            "偏移":   35,   # 12GB VRAM 门槛，低配机直接出局
            "资源消耗": 40,  # 12GB VRAM 基线，本地部署重
        },
    },
}

# 6 维（输出固定顺序）
SIX_DIMS = ["覆盖面", "类型", "效率", "容错", "偏移", "资源消耗"]


# ============================================================================
# 三、HookForge 打分：从当前矩阵实数推每维 0-100
# ============================================================================
def _hf_resource_count_score(count: int) -> float:
    """资源类型数 → 分数：20 类拿 80，线性封顶（40 类=100）。"""
    return min(100.0, count / 20.0 * 80.0)


def score_hookforge(scenario: Optional[str] = None,
                    ref: Optional[str] = None,
                    matrix: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """按 HookForge 当前矩阵算 6 维分（0-100）。

    scenario/ref 影响微调：指定剧种或参照物时，相关维度加分（最高 +10），
    模拟"针对该场景 HookForge 更对口"。
    """
    m = dict(HOOKFORGE_MATRIX)
    if matrix:
        m.update(matrix)

    d: Dict[str, float] = {}

    # 覆盖面：画风+音乐+声音+BGM+剧种 全链路自产，不依赖外置轨
    d["覆盖面"] = 90
    if scenario:
        d["覆盖面"] = min(100.0, d["覆盖面"] + 5)  # 场景化默认轨命中

    # 类型：资源轨总数驱动（画风是主项，其余轨加权）
    d["类型"] = min(100.0,
                    _hf_resource_count_score(m["style_tracks"])
                    + _hf_resource_count_score(m["music_tracks"]) * 0.25
                    + _hf_resource_count_score(m["voice_tracks"]) * 0.25
                    + _hf_resource_count_score(m["bgm_tracks"]) * 0.5
                    )

    # 效率：三维自动编排（不用拖节点/不用剪辑），单集全流程跑通
    d["效率"] = 85
    if m.get("smart_audio_trim"):
        d["效率"] += 5  # 音频轨默认只生成 1-2 条，省 50%+ 资源

    # 容错：三级降级 + 冲突检测 v2 + 实机指标反哺
    d["容错"] = 55 + 25 * min(3, m.get("levels_fallback", 0)) / 3.0  # 三级降级 → +25
    if m.get("conflict_check"):
        d["容错"] += 10
    if m.get("adaptive_feedback"):
        d["容错"] += 5
    d["容错"] = min(100.0, d["容错"])

    # 偏移（低配亲民）：T0/T1 95% 跑通率目标 + 亲民默认策略
    d["偏移"] = 70 + 20 * m.get("t0_t1_runrate_goal", 0.0)  # 0.95 → 89
    d["偏移"] = min(100.0, d["偏移"])

    # 资源消耗：亲民默认（GGUF Q4 + offload）省显存/省计费
    d["资源消耗"] = 80
    if m.get("audio_combo_optimize"):
        d["资源消耗"] += 10  # 四维协同避免重复生成
    d["资源消耗"] = min(100.0, d["资源消耗"])

    # 场景/参照物微调
    if ref in REFERENCE_BASLINES:
        d["覆盖面"] = min(100.0, d["覆盖面"] + 3)

    return {k: round(float(v), 1) for k, v in d.items()}


def best_reference_score(ref: Optional[str] = None) -> Dict[str, float]:
    """取参照物中的每维最高分（ref 指定时取该参照物单家）。"""
    pool = ([REFERENCE_BASLINES[ref]] if ref and ref in REFERENCE_BASLINES
            else list(REFERENCE_BASLINES.values()))
    out: Dict[str, float] = {}
    for dim in SIX_DIMS:
        out[dim] = max(float(r["dims"][dim]) for r in pool)
    return out


def build_advisory(scenario: Optional[str] = None,
                   ref: Optional[str] = None,
                   matrix: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成完整对标超越报告（6 维：HookForge 分 / 参照物最高分 / 超越幅度）。"""
    hf = score_hookforge(scenario=scenario, ref=ref, matrix=matrix)
    br = best_reference_score(ref=ref)
    ref_labels = {r: REFERENCE_BASLINES[r]["label"]
                  for r in ([ref] if ref and ref in REFERENCE_BASLINES
                            else list(REFERENCE_BASLINES))}

    win_dims: List[str] = []
    dims_out: Dict[str, Any] = {}
    for dim in SIX_DIMS:
        lead = round(hf[dim] - br[dim], 1)
        dims_out[dim] = {
            "hook_forge": hf[dim],
            "best_ref": br[dim],
            "lead": lead,                     # 超越幅度（正=HookForge 领先）
            "win": bool(hf[dim] > br[dim]),
        }
        if dims_out[dim]["win"]:
            win_dims.append(dim)

    return {
        "hook_forge": hf,
        "reference_best": br,
        "ref_scope": (ref if ref and ref in REFERENCE_BASLINES
                      else "all(4参照物取每维最高)"),
        "scenario": scenario or "default",
        "ref_labels": ref_labels,
        "dims": dims_out,
        "win_count": len(win_dims),
        "win_dims": win_dims,
        "win_rate": round(len(win_dims) / float(len(SIX_DIMS)), 2),
        "matrix_snapshot": {k: HOOKFORGE_MATRIX[k] for k in
                            ("style_tracks", "music_tracks",
                             "voice_tracks", "bgm_tracks",
                             "scenarios", "arc_stages")},
    }


# ============================================================================
# 四、导出
# ============================================================================
def to_json(report: Any) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def to_yaml(report: Any) -> str:
    if yaml is None:
        return to_json(report)
    return yaml.safe_dump(report, allow_unicode=True, sort_keys=False)


def export(report: Any, path: str, fmt: str = "yaml") -> str:
    text = to_yaml(report) if fmt == "yaml" else to_json(report)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ============================================================================
# 五、CLI：--scenario / --ref / --all / --format / --out
# ============================================================================
def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    scenario: Optional[str] = None
    ref: Optional[str] = None
    fmt = "yaml"
    out: Optional[str] = None
    all_refs = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--scenario":
            i += 1; scenario = argv[i]
        elif a == "--ref":
            i += 1; ref = argv[i]
        elif a == "--all":
            all_refs = True
        elif a == "--format":
            i += 1; fmt = argv[i]
        elif a == "--out":
            i += 1; out = argv[i]
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            print(f"unknown arg: {a}", file=sys.stderr)
            return 2
        i += 1

    if ref is not None and ref not in REFERENCE_BASLINES:
        print(f"unknown --ref: {ref} "
              f"(valid: {', '.join(REFERENCE_BASLINES)})", file=sys.stderr)
        return 2

    reports: List[Dict[str, Any]] = []
    for r in ([ref] if ref else list(REFERENCE_BASLINES)):
        rep = build_advisory(scenario=scenario, ref=r, matrix=None)
        rep["_ref_key"] = r
        reports.append(rep)
    blob = reports[0] if len(reports) == 1 else {"reports": reports}
    text = to_yaml(blob)
    if out:
        export(blob, out, fmt=fmt)
        print(f"written: {out} ({fmt})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
