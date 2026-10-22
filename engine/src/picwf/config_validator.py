# -*- coding: utf-8 -*-
"""matrix.yaml 结构 + 交叉引用校验（配置规范化）。

手写 YAML 缺 schema 校验的三大风险：
  1) 键名拼错 / 档位缺口（某 node 的 fallback_chain 缺 T0 或 T2）
  2) 交叉引用悬空（画风 image_model 引用了不存在的模型名）
  3) 数值非法（estimated_vram_need_gb 负数 / 不在 tiers 阈值区间）

本模块离线校验，不写任何文件，输出 error/warn 列表。
集成点：CI 跑一次 validate_matrix()，有 error 则 fail。
"""
from typing import Any, Dict, List, Tuple

REQUIRED_TOP_KEYS = ["version", "tiers", "nodes"]
REQUIRED_NODE_FIELDS = ["id", "fallback_chain"]
REQUIRED_TIER = ["T0", "T1", "T2"]   # MVP 最低三档必须齐全
VRAM_IMPL_HINTS = {
    "cloud": ("cloud", "kling", "seedream", "api", "grok"),
    "gguf_offload": ("gguf", "offload"),
}


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

    return {"errors": errors, "warnings": warnings}


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
