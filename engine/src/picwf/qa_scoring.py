# -*- coding: utf-8 -*-
"""镜头质检 4 维打分（纯逻辑层，可单测，不依赖 torch/CLIP 实模型）。

输入：一个镜头的观测指标（数值），输出：形变/质变/迁移/偏移 4 维打分 + 综合判定。
真实场景里这些观测指标由 shot_qa.py 用 CLIP 相似度 + 时长合规 + 关键帧提取产出，
本模块负责"打分→阈值判定→路由（重做/云端精修/通过）"。

4 维定义（值 0~1，越高越好）：
- 形变 consistency_shape  : 角色面部/服装前后帧一致性（CLIP 角色锚相似度）
- 质变 consistency_style  : 画风/色调稳定性（画风 LUT 前后偏差）
- 迁移 continuity_place   : 场景/时代/世界观连贯（场景参考图 CLIP 相似度）
- 偏移 alignment_intent   : 生成结果 vs 期望 prompt 的偏离（CLIP 文图相似度）
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

# 默认阈值（可被 SOP/视频导演覆盖）
DEFAULT_THRESH = {
    "consistency_shape": 0.85,  # 形变下限
    "consistency_style": 0.80,  # 质变下限
    "continuity_place":  0.78,  # 迁移下限
    "alignment_intent":  0.82,  # 偏移下限
}

# 档位感知阈值：高端档(T2+)画质要求严，低配档(T0/T1 云端/量化)容忍度高。
# 未列出的档位用 DEFAULT_THRESH。
TIER_THRESH = {
    "T0": {"consistency_shape": 0.80, "consistency_style": 0.75,
           "continuity_place": 0.72, "alignment_intent": 0.78},
    "T1": {"consistency_shape": 0.83, "consistency_style": 0.78,
           "continuity_place": 0.75, "alignment_intent": 0.80},
    "T2": {"consistency_shape": 0.88, "consistency_style": 0.83,
           "continuity_place": 0.80, "alignment_intent": 0.85},
}


def thresh_for_tier(tier: str, override: Dict[str, float] = None) -> Dict[str, float]:
    """按档位取阈值（默认 T1 基线），可被显式 override 覆盖。"""
    base = dict(TIER_THRESH.get(tier, DEFAULT_THRESH))
    if override:
        base.update(override)
    return base


@dataclass
class ShotMetrics:
    """镜头观测指标（0~1）。duration 为绝对值秒。"""
    consistency_shape: float = 1.0
    consistency_style: float = 1.0
    continuity_place: float = 1.0
    alignment_intent: float = 1.0
    duration_s: float = 5.0
    expected_duration_s: float = 5.0
    keyframe_drift: float = 0.0  # 关键帧跳变幅度，0~1，越大越差
    shot_id: str = "unknown"   # 镜头/节点 id，用于重做队列定位


@dataclass
class QAReport:
    scores: Dict[str, float] = field(default_factory=dict)
    duration_compliant: bool = True
    overall: float = 0.0
    passed: bool = True
    route: str = "pass"      # pass / redo_local / cloud_refine
    reasons: List[str] = field(default_factory=list)
    metrics: Any = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "scores": self.scores,
            "duration_compliant": self.duration_compliant,
            "overall": self.overall,
            "passed": self.passed,
            "route": self.route,
            "reasons": self.reasons,
        }


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def score_shot(m: ShotMetrics,
               thresh: Dict[str, float] = None,
               duration_tolerance_s: float = 2.0,
               tier: str = "T1") -> QAReport:
    """对单镜头打分并路由。

    路由规则：
    - 4 维全部 >= 阈值 且 时长合规 -> pass
    - 任一维 < 阈值:
        - 偏移/迁移 严重（< 阈值*0.85）或时长不合规 -> cloud_refine（切云端精修）
        - 其余 -> redo_local（本地重做）
    """
    # 档位感知阈值：显式传入 thresh 优先，否则按档位取
    th = thresh if thresh else thresh_for_tier(tier)
    if not th:
        th = dict(DEFAULT_THRESH)

    scores = {
        "consistency_shape": _clamp(m.consistency_shape),
        "consistency_style": _clamp(m.consistency_style),
        "continuity_place": _clamp(m.continuity_place),
        "alignment_intent": _clamp(m.alignment_intent),
    }
    # 关键帧跳变扣到形变维（跳变越大形变分越低）
    scores["consistency_shape"] = _clamp(
        scores["consistency_shape"] - 0.3 * _clamp(m.keyframe_drift))

    # 时长合规
    delta = abs(m.duration_s - m.expected_duration_s)
    duration_compliant = delta <= duration_tolerance_s

    # 综合分（等权，时长不合规再扣 10%）
    overall = round(sum(scores.values()) / 4.0, 4)
    if not duration_compliant:
        overall = round(overall * 0.9, 4)

    passed = True
    reasons: List[str] = []
    for k, v in scores.items():
        if v < th.get(k, DEFAULT_THRESH.get(k, 0.8)):
            passed = False
            reasons.append(f"{k}={v:.3f} < {th.get(k)}")

    # 路由
    if passed and duration_compliant:
        route = "pass"
    else:
        # 严重项判定：偏移/迁移 低于阈值*0.85 视为需云端精修
        severe = (
            scores["alignment_intent"] < th.get("alignment_intent", .82) * 0.85
            or scores["continuity_place"] < th.get("continuity_place", .78) * 0.85
        )
        route = "cloud_refine" if (severe or not duration_compliant) else "redo_local"

    return QAReport(
        scores=scores,
        duration_compliant=duration_compliant,
        overall=overall,
        passed=passed,
        route=route,
        reasons=reasons,
        metrics=m,
    )


def build_requeue(reports: List[QAReport]) -> Dict[str, List[str]]:
    """把未通过镜头按路由分桶，进重做队列/云端精修队列。"""
    buckets: Dict[str, List[str]] = {"pass": [], "redo_local": [], "cloud_refine": []}
    for r in reports:
        sid = getattr(r.metrics, "shot_id", "unknown")
        buckets[r.route].append(str(sid))
    return buckets
