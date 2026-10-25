# -*- coding: utf-8 -*-
"""lora_train：角色 LoRA 训练闭环（行业前3的"锁脸"终极方案）。

character_consistency 用"三视图锚定 + 人脸相似度"控单集/跨集一致性，
但行业前3 是**给主角训专属 LoRA**，把脸/服装/气质烙进模型权重，
后续每镜挂这张 LoRA 出图，脸从根上不漂。本模块做训练闭环（规划+采样+调度）：

1. plan_lora_training(chars) -> 给哪些角色训 LoRA（按戏份权重排序），
   返回训练方案（每角色 sample 数/分辨率/epoch/lr 按数据量估）。
2. collect_lora_dataset(workdir, char) -> 聚合该角色已有的三视图 + 出片截图，
   按 caption 模板组织训练集。
3. lora_train_plan(chars, history) -> 综合方案（优先级 + 资源需求 + 训练时长估）。

设计：本模块只做"规划 + 数据聚合 + 调度"（离线可跑），真正的 torch 训练
由外部执行（本环境无 GPU 训练栈），保证不依赖实模型也能验证链路。
和 character_consistency 互补：三视图锚定是"轻"，LoRA 是"重但更稳"。
"""
from typing import Dict, List, Any, Optional

# 戏份权重（决定要不要训 + 训练强度）
_ROLE_WEIGHT = {"主角": 3.0, "反派": 2.0, "女主": 3.0, "男主": 3.0, "配角": 1.0, "龙套": 0.5}

# 数据量 -> 训练参数（粗略经验值）
_TRAIN_PARAMS = [
    # (min_samples, epoch, lr, 建议分辨率)
    (10, 8, 1e-4, 512),
    (20, 12, 5e-5, 768),
    (40, 16, 2e-5, 1024),
]


def _data_tier(n_samples: int) -> int:
    tier = 0
    for i, (mins, *_ ) in enumerate(_TRAIN_PARAMS):
        if n_samples >= mins:
            tier = i
    return tier


def plan_lora_training(chars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给角色排 LoRA 训练优先级 + 参数。

    chars: [{name, role, n_samples(已有可用素材数), has_three_view}]
    返回按"该训优先级"降序的 [{char, role, priority, train, samples,
      epoch, lr, res, estimated_min}]。戏份重 + 素材足 -> 先训、训足。
    """
    plans = []
    for c in chars:
        role = c.get("role", "配角")
        n = int(c.get("n_samples", 0))
        weight = _ROLE_WEIGHT.get(role, 1.0)
        # 戏份 >= 反派/主角 且素材 >= 10 才值得训
        worth = weight >= 2.0 and n >= 10
        tier = _data_tier(n)
        mins, epoch, lr, res = _TRAIN_PARAMS[min(tier, len(_TRAIN_PARAMS) - 1)]
        # 训练时长粗估（分钟）= epoch * samples * 单张 3s
        est_min = round(epoch * max(n, mins) * 3.0 / 60.0, 1)
        plans.append({
            "char": c.get("name"), "role": role, "priority": round(weight, 1),
            "worth_training": worth, "samples": n, "min_samples": mins,
            "epoch": epoch, "lr": lr, "res": res, "estimated_min": est_min,
            "has_three_view": bool(c.get("has_three_view")),
            "reason": (f"戏份 {role}(w={weight}) + 素材 {n} 张"
                       + (f"（>= {mins}，可训 {res}p/{epoch}ep）" if worth else "（素材不足或戏份轻，建议先三视图锚定）")),
        })
    plans.sort(key=lambda x: (-x["priority"], -x["samples"]))
    return plans


def collect_lora_dataset(workdir: str, char: Dict[str, Any]) -> Dict[str, Any]:
    """聚合角色训练集（三视图 + 出片截图 + caption 模板）。

    返回 {char, images:[path], captions:[...], n, ready}。
    caption 用 character_consistency 的外观锁定描述，让 LoRA 学"长相"不学"剧情"。
    """
    import os
    from .character_consistency import build_character_block
    name = char.get("name", "char")
    # 候选素材：三视图 + 历史出片角色截图
    cand = [
        f"{workdir}/char_ref_{name}_3view.png",
        f"{workdir}/char_ref_{name}_front.png",
    ] + [f"{workdir}/shots/{name}_s{i}.png" for i in range(6)]
    images = [p for p in cand if os.path.exists(p)]
    block = build_character_block(char, lang="bilingual")
    # caption 模板：强调外观锁，不强调剧情
    caption_tpl = (f"{name}, consistent face and outfit reference, "
                   f"character consistency anchor. {block}")
    n = len(images)
    return {"char": name, "images": images, "captions": [caption_tpl] * n,
            "n": n, "ready": n >= 10,
            "note": "素材 <10 张时 LoRA 过拟合风险高，建议补三视图 + 多角度截图"}


def lora_train_plan(chars: List[Dict[str, Any]],
                    workdir: str = "",
                    available_gpus: int = 1) -> Dict[str, Any]:
    """综合训练方案：优先级 + 资源需求 + 总时长（可多卡并行摊薄）。

    返回 {plans, total_est_min, parallel_minutes, need_gpus,
           recommend:[应训角色]}。
    """
    plans = plan_lora_training(chars)
    to_train = [p for p in plans if p["worth_training"]]
    total = sum(p["estimated_min"] for p in to_train)
    par = max(1, min(available_gpus, len(to_train)))
    parallel_minutes = round(total / par, 1) if total else 0.0
    return {
        "plans": plans, "recommend": [p["char"] for p in to_train],
        "n_recommended": len(to_train), "total_est_min": round(total, 1),
        "parallel_minutes": parallel_minutes, "need_gpus": par,
        "dataset_ready": {p["char"]: collect_lora_dataset(workdir, {"name": p["char"]})["ready"]
                           for p in to_train} if workdir else {},
        "note": "先训 recommend 里的角色；训练后 character_image 环节挂该 LoRA，脸从权重级锁死",
    }
