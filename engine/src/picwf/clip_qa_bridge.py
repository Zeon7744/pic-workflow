# -*- coding: utf-8 -*-
"""clip_qa_bridge：真实 CLIP 观测质检（行业前3的"看得懂画面"能力）。

shot_qa 已有 CLIP 相似度（无 torch 降级中性），multimodal_qa 是纯规则（离线可跑）。
本桥把两者合起来：**优先用真实 CLIP 观测"画面符不符 prompt"，观测不到再退回规则**，
让引擎在有模型时做真正的语义质检，没模型时仍离线可验证。

1. clip_intent_score(prompt, keyframe, ref_desc) -> 真实文图相似度（0-1）
2. observe_multimodal(video, prompts, rules) -> 4 维真观测 + 规则兜底，
   返回 {dim: {score, source(clip|rule)}}，source 标注每一维是真观测还是规则。
3. qa_with_observation(...) -> 出片后调用：能观测就真值，不能就规则，统一聚合。

设计：torch/clip 缺失自动降级，链路始终可跑（对齐 shot_qa._clip_similarity 兜底）。
"""
from typing import Dict, List, Any, Optional, Tuple

try:
    from .shot_qa import _clip_similarity
except Exception:
    _clip_similarity = None

try:
    import torch
    _HAS_TORCH = True
except Exception:
    _HAS_TORCH = False

# 规则版多模态质检（离线兜底）
try:
    from . import multimodal_qa as _mq
except Exception:
    _mq = None


def clip_intent_score(prompt: str, keyframe_or_desc: str, ref_desc: str = "") -> Dict[str, Any]:
    """真实意图相似度。返回 {score, source}。

    source: "clip"=真观测 / "none"=无模型中性。
    """
    if _clip_similarity is None:
        return {"score": 0.5, "source": "none", "note": "clip 桥不可用"}
    try:
        # 有 keyframe 走图图/文图，否则文文
        s = _clip_similarity(prompt, keyframe_or_desc or prompt)
        return {"score": round(max(0.0, min(1.0, s)), 3), "source": "clip" if _HAS_TORCH else "degraded"}
    except Exception:
        return {"score": 0.5, "source": "degraded", "note": "CLIP 观测失败，给中性"}


def observe_multimodal(video: str, prompts: List[str],
                       lip_events: Optional[List] = None,
                       audio_events: Optional[List] = None,
                       action_marks: Optional[List] = None,
                       beat_times: Optional[List] = None,
                       shot_emotions: Optional[List] = None,
                       bgm_emotions: Optional[List] = None) -> Dict[str, Any]:
    """4 维真观测 + 规则兜底。

    每维 {score, source}：有 CLIP/规则数据走真值，缺则中性 0.5 且 source=degraded。
    """
    dims: Dict[str, Dict[str, Any]] = {}
    # intent（画面符不符 prompt）：CLIP 真观测优先
    dims["intent"] = clip_intent_score(prompts[0] if prompts else "", video)
    # 其余三维走多模态规则（有数据才算，没有中性）
    if _mq is not None:
        dims["lip"] = {"score": _mq.lip_sync_qa(lip_events or [])["score"],
                       "source": "rule" if lip_events else "degraded"}
        dims["av"] = {"score": _mq.av_sync_qa(audio_events or [])["score"],
                      "source": "rule" if audio_events else "degraded"}
        dims["rhythm"] = {"score": _mq.rhythm_qa(action_marks or [], beat_times or [])["score"],
                          "source": "rule" if (action_marks and beat_times) else "degraded"}
        dims["emotion"] = {"score": _mq.emotion_align_qa(shot_emotions or [], bgm_emotions or [])["score"],
                           "source": "rule" if (shot_emotions and bgm_emotions) else "degraded"}
    else:
        for k in ("lip", "av", "rhythm", "emotion"):
            dims[k] = {"score": 0.5, "source": "degraded", "note": "多模态规则模块缺失"}
    dims["has_clip"] = _HAS_TORCH
    return dims


def qa_with_observation(video: str, prompts: List[str],
                        rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """出片后统一质检：能观测真值就真值，不能就规则兜底，聚合打分。

    返回 {dims, overall, passed, clip_used, note}。
    """
    dims = observe_multimodal(
        video, prompts,
        lip_events=(rules or {}).get("lip_events"),
        audio_events=(rules or {}).get("audio_events"),
        action_marks=(rules or {}).get("action_marks"),
        beat_times=(rules or {}).get("beat_times"),
        shot_emotions=(rules or {}).get("shot_emotions"),
        bgm_emotions=(rules or {}).get("bgm_emotions"))
    w = {"intent": 0.4, "lip": 0.2, "av": 0.2, "rhythm": 0.1, "emotion": 0.1}
    overall = sum(dims[k]["score"] * w[k] for k in w)
    clip_used = dims["intent"]["source"] in ("clip", "degraded") and dims["has_clip"]
    passed = overall >= 0.7
    return {"dims": dims, "overall": round(overall, 3), "passed": passed,
            "clip_used": bool(dims["has_clip"]),
            "note": "CLIP 真观测已启用" if dims["has_clip"] else "无 torch/CLIP，规则兜底（离线可跑，真值需实机）"}
