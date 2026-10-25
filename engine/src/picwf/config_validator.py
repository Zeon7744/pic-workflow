# -*- coding: utf-8 -*-
"""matrix.yaml 结构 + 交叉引用校验（配置规范化）。

手写 YAML 缺 schema 校验的三大风险：
  1) 键名拼错 / 档位缺口（某 node 的 fallback_chain 缺 T0 或 T2）
  2) 交叉引用悬空（画风 image_model 引用了不存在的模型名）
  3) 数值非法（estimated_vram_need_gb 负数 / 不在 tiers 阈值区间）

本模块离线校验，不写任何文件，输出 error/warn 列表。
集成点：CI 跑一次 validate_matrix()，有 error 则 fail。

0.5.13 起新增 4 个叙事/交付维度（shot_patterns / platform_profiles /
hook_patterns / pace_profiles）的交叉引用校验：这些维度之间互指
（平台→节奏档/钩子、节奏档→BGM、镜型→节拍），任一处改名或删除都会
造成悬空，必须在 CI 阶段拦住。
"""
from typing import Any, Dict, List, Tuple

REQUIRED_TOP_KEYS = ["version", "tiers", "nodes"]
REQUIRED_NODE_FIELDS = ["id", "fallback_chain"]
REQUIRED_TIER = ["T0", "T1", "T2"]   # MVP 最低三档必须齐全
VRAM_IMPL_HINTS = {
    "cloud": ("cloud", "kling", "seedream", "api", "grok"),
    "gguf_offload": ("gguf", "offload"),
}

# 0.5.13 新增维度：各自的必备字段
NARRATIVE_DIM_FIELDS = {
    "shot_patterns": ["label", "shot_size", "camera_move", "est_s", "beats", "intensity"],
    "platform_profiles": ["label", "aspect_ratio", "resolution", "fps",
                          "min_duration_s", "max_duration_s", "pace_profile",
                          "primary_hooks", "platform_tags", "max_file_mb",
                          "title_max_len", "subtitle_safe_area"],
    "hook_patterns": ["label", "hook_type", "beat", "deadline_s", "score_floor",
                      "emotion", "promise", "hook_3s", "hook_15s"],
    "pace_profiles": ["label", "target_episode_s", "cut_per_min", "payoff_per_ep",
                      "sweet_per_ep", "shot_avg_s", "intensity", "bgm_pref",
                      "style_pref", "hook_types", "shot_patterns", "scenarios"],
}

# 集结构角色（与 narrative_architect.BEAT_ROLES 对齐；此处独立声明避免循环依赖）
NARRATIVE_BEATS = ["hook", "setup", "escalate", "payoff", "sweet", "twist", "cliff"]


def _impl_class(impl: str) -> str:
    s = (impl or "").lower()
    for cls, keys in VRAM_IMPL_HINTS.items():
        if any(k in s for k in keys):
            return cls
    return "local"


def validate_matrix(matrix: Dict[str, Any]) -> Dict[str, List[str]]:
    """校验 matrix，返回 {"errors": [...], "warnings": [...]}。

    校验项：
      - 顶层必备键
      - tiers 至少含 T0/T1/T2
      - 每个 node 有 id + fallback_chain
      - 每 node 的 fallback_chain 至少覆盖 MVP 三档
      - 交叉引用：style_tracks 的 image/video_model 里的模型，
        至少有一个能在某 node 的 fallback_chain 里找到（否则悬空）
      - estimated_vram_need_gb 非负
      - 音频轨 label 非空（历史上出现过畸形 key 导致值全 null）
      - 0.5.13：shot_patterns / platform_profiles / hook_patterns /
        pace_profiles 必备字段、互指关系、编号连续性、数值区间
    """
    errors: List[str] = []
    warnings: List[str] = []

    # 1) 顶层必备键
    for k in REQUIRED_TOP_KEYS:
        if k not in matrix:
            errors.append(f"缺少顶层键 {k}")

    tiers = matrix.get("tiers", {})
    for t in REQUIRED_TIER:
        if t not in tiers:
            errors.append(f"tiers 缺少 {t}（MVP 最低三档）")

    nodes = matrix.get("nodes", [])
    if not nodes:
        errors.append("nodes 为空")

    # 2) 每个 node 结构 + 档位覆盖
    known_impls = set()
    for n in nodes:
        nid = n.get("id", "<missing>")
        if "id" not in n:
            errors.append(f"node 缺 id: {nid}")
            continue
        if "fallback_chain" not in n:
            errors.append(f"node {nid} 缺 fallback_chain")
            continue
        chain = n["fallback_chain"]
        covered = set()
        for tier_key, levels in chain.items():
            covered.add(tier_key)
            for lvl in (levels or []):
                impl = lvl.get("impl")
                if impl:
                    known_impls.add(impl)
                v = lvl.get("estimated_vram_need_gb")
                if v is not None and v < 0:
                    errors.append(f"node {nid}/{tier_key} 的 {impl} vram_need 负数 {v}")
        missing_tiers = set(REQUIRED_TIER) - covered
        if missing_tiers:
            errors.append(f"node {nid} fallback_chain 缺档位 {sorted(missing_tiers)}")

    # 3) 交叉引用：画风模型是否有落地（在某 node chain 出现过）
    for dim in ("style_tracks", "music_tracks", "voice_tracks", "bgm_tracks"):
        for key, track in (matrix.get(dim) or {}).items():
            for md in ("image_model", "video_model"):
                for impl in (track.get(md) or []):
                    if impl not in known_impls:
                        # 画风轨模型名与 node 里 impl 不一致 → 悬空警告
                        warnings.append(
                            f"{dim}.{key}.{md} 引用 {impl} 未在任何 node fallback_chain 出现")

    # 3b) 音频轨字段完整性：label 必须有值（历史上出现过畸形 key 导致值全 null）
    for dim in ("music_tracks", "voice_tracks", "bgm_tracks"):
        for key, track in (matrix.get(dim) or {}).items():
            if not isinstance(track, dict) or not track.get("label"):
                errors.append(f"{dim}.{key} 缺 label（维度数据损坏）")

    errors.extend(_validate_narrative_dims(matrix))
    return {"errors": errors, "warnings": warnings}


def _validate_narrative_dims(matrix: Dict[str, Any]) -> List[str]:
    """0.5.13 新增 4 维度的结构 + 互指校验，返回 error 列表。"""
    errors: List[str] = []

    shot_patterns = matrix.get("shot_patterns") or {}
    platform_profiles = matrix.get("platform_profiles") or {}
    hook_patterns = matrix.get("hook_patterns") or {}
    pace_profiles = matrix.get("pace_profiles") or {}

    for dim, block in (("shot_patterns", shot_patterns),
                       ("platform_profiles", platform_profiles),
                       ("hook_patterns", hook_patterns),
                       ("pace_profiles", pace_profiles)):
        if not block:
            errors.append(f"缺少维度 {dim}")
            continue
        for key, item in block.items():
            for field in NARRATIVE_DIM_FIELDS[dim]:
                if not isinstance(item, dict) or field not in item:
                    errors.append(f"{dim}.{key} 缺字段 {field}")

    # 3c) 镜型：节拍角色合法 + 编号连续
    for key, item in shot_patterns.items():
        beats = (item or {}).get("beats") or []
        for b in beats:
            if b not in NARRATIVE_BEATS:
                errors.append(f"shot_patterns.{key}.beats 引用未知节拍 {b}")
        inten = (item or {}).get("intensity")
        if inten is not None and not (1 <= int(inten) <= 5):
            errors.append(f"shot_patterns.{key}.intensity 越界 {inten}（应为 1-5）")
        est = (item or {}).get("est_s")
        if est is not None and float(est) <= 0:
            errors.append(f"shot_patterns.{key}.est_s 非正 {est}")
    errors.extend(_check_numbering("shot_patterns", shot_patterns, "SP"))
    errors.extend(_check_numbering("pace_profiles", pace_profiles, "PC"))

    # 3d) 钩子：hook_type 与自身 key 一致 + 节拍合法 + 分值区间
    for key, item in hook_patterns.items():
        if (item or {}).get("hook_type") != key:
            errors.append(f"hook_patterns.{key}.hook_type 与 key 不一致"
                          f"（{item.get('hook_type')}）")
        beat = (item or {}).get("beat")
        if beat and beat not in NARRATIVE_BEATS:
            errors.append(f"hook_patterns.{key}.beat 引用未知节拍 {beat}")
        dl = (item or {}).get("deadline_s")
        if dl is not None and not (0 < float(dl) <= 15):
            errors.append(f"hook_patterns.{key}.deadline_s 越界 {dl}（应为 1-15s）")
        floor = (item or {}).get("score_floor")
        if floor is not None and not (0 <= float(floor) <= 100):
            errors.append(f"hook_patterns.{key}.score_floor 越界 {floor}")

    # 3e) 平台档案：指向的节奏档与钩子必须存在
    for key, item in platform_profiles.items():
        pace = (item or {}).get("pace_profile")
        if pace and pace not in pace_profiles:
            errors.append(f"platform_profiles.{key}.pace_profile 引用不存在的节奏档 {pace}")
        for hook in (item or {}).get("primary_hooks") or []:
            if hook not in hook_patterns:
                errors.append(
                    f"platform_profiles.{key}.primary_hooks 引用不存在的钩子 {hook}")
        # 3 秒钩子铁律：每个平台至少要有一个 3 秒内能爆发的钩子
        quick = [h for h in ((item or {}).get("primary_hooks") or [])
                 if h in hook_patterns
                 and float((hook_patterns[h] or {}).get("deadline_s") or 99) <= 3]
        if (item or {}).get("primary_hooks") and not quick:
            errors.append(
                f"platform_profiles.{key} 没有任何 3 秒内钩子（违反钩子铁律）")
        mn = (item or {}).get("min_duration_s")
        mx = (item or {}).get("max_duration_s")
        if mn is not None and mx is not None and int(mn) > int(mx):
            errors.append(f"platform_profiles.{key} 时长区间非法 min={mn} > max={mx}")

    # 3f) 节奏档：BGM/画风/钩子/镜型/题材 偏好必须存在 + 数值区间
    bgm_keys = set((matrix.get("bgm_tracks") or {}).keys())
    style_keys = set((matrix.get("style_tracks") or {}).keys())
    scenario_keys = set((matrix.get("scenario_resource_map") or {}).keys())
    for key, item in pace_profiles.items():
        bgm = (item or {}).get("bgm_pref")
        if bgm and bgm not in bgm_keys:
            errors.append(f"pace_profiles.{key}.bgm_pref 引用不存在的 BGM {bgm}")
        style = (item or {}).get("style_pref")
        if style and style not in style_keys:
            errors.append(f"pace_profiles.{key}.style_pref 引用不存在的画风 {style}")
        for h in (item or {}).get("hook_types") or []:
            if h not in hook_patterns:
                errors.append(f"pace_profiles.{key}.hook_types 引用不存在的钩子 {h}")
        for sp in (item or {}).get("shot_patterns") or []:
            if sp not in shot_patterns:
                errors.append(f"pace_profiles.{key}.shot_patterns 引用不存在的镜型 {sp}")
        for sc in (item or {}).get("scenarios") or []:
            if sc not in scenario_keys:
                errors.append(f"pace_profiles.{key}.scenarios 引用不存在的题材 {sc}")
        payoff = (item or {}).get("payoff_per_ep")
        if payoff is not None and int(payoff) < 3:
            errors.append(f"pace_profiles.{key}.payoff_per_ep={payoff} 低于每集 3 爽点铁律")
        sweet = (item or {}).get("sweet_per_ep")
        if sweet is not None and int(sweet) < 1:
            errors.append(f"pace_profiles.{key}.sweet_per_ep={sweet} 低于每集 1 甜点铁律")
        for field, lo, hi in (("target_episode_s", 15, 600), ("cut_per_min", 1, 200),
                              ("payoff_per_ep", 0, 20), ("sweet_per_ep", 0, 20),
                              ("shot_avg_s", 0.1, 60)):
            v = (item or {}).get(field)
            if v is not None and not (lo <= float(v) <= hi):
                errors.append(f"pace_profiles.{key}.{field} 越界 {v}（应在 {lo}-{hi}）")
        inten = (item or {}).get("intensity")
        if inten is not None and not (1 <= int(inten) <= 5):
            errors.append(f"pace_profiles.{key}.intensity 越界 {inten}（应为 1-5）")

    return errors


def _check_numbering(dim: str, block: Dict[str, Any], prefix: str) -> List[str]:
    """检查同一维度内编号是否连续（SP1..SP24 不能跳号或重号）。"""
    errors: List[str] = []
    nums = []
    for key in block:
        k = str(key)
        if not k.startswith(prefix):
            errors.append(f"{dim}.{key} 编号前缀应为 {prefix}")
            continue
        tail = k[len(prefix):]
        head = ""
        for ch in tail:
            if ch.isdigit():
                head += ch
            else:
                break
        if not head:
            errors.append(f"{dim}.{key} 编号缺失数字段")
            continue
        nums.append((int(head), key))
    nums.sort()
    for i, (n, key) in enumerate(nums, start=1):
        if n != i:
            errors.append(f"{dim} 编号不连续：{key} 期望 {prefix}{i} 实际 {prefix}{n}")
            break
    return errors


def validate_matrix_file(path: str) -> Dict[str, List[str]]:
    import yaml
    with open(path, encoding="utf-8") as f:
        return validate_matrix(yaml.safe_load(f))


def main():
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    import os
    default = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "config", "matrix.yaml")
    res = validate_matrix_file(path or default)
    print(f"errors={len(res["errors"])} warnings={len(res["warnings"])}")
    for e in res["errors"]:
        print("  [E]", e)
    for w in res["warnings"][:20]:
        print("  [W]", w)
    sys.exit(1 if res["errors"] else 0)


if __name__ == "__main__":
    main()
