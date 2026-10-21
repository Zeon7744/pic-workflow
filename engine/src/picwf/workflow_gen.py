# -*- coding: utf-8 -*-
"""工作流生成器：按档位裁剪 8 环节节点，选模型/参数/量化精度。

读 config/matrix.yaml + 档位 → 输出一份"这台机器能跑通"的工作流 YAML。
YAML 是数据不是代码：同一份生成器，换一份 matrix.yaml 就是换个工作流。
"""
import os
from typing import Any, Dict, List

try:
    import yaml
except Exception:
    yaml = None  # 运行时才需要；缺失时给出提示

MATRIX_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "matrix.yaml")


def _load_yaml(path):
    if yaml is None:
        raise RuntimeError("缺少 PyYAML，请 pip install pyyaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def generate_workflow(tier: str, matrix_path: str = MATRIX_PATH_DEFAULT,
                      free_vram_gb: float = 99.0) -> Dict[str, Any]:
    """生成指定档位的工作流。

    tier: T0/T1/T2（MVP）
    free_vram_gb: 运行时可用显存，用于预筛每节点 fallback 的起始级别。
    返回结构化 workflow（可序列化为 YAML）。
    """
    matrix = _load_yaml(matrix_path)
    tier_name = tier.upper()
    if tier_name not in matrix.get("tiers", {}):
        raise KeyError(f"未知档位 {tier_name}，可用: {list(matrix['tiers'].keys())}")

    nodes: List[Dict[str, Any]] = []
    for node in matrix["nodes"]:
        chain = node.get("fallback_chain", {}).get(tier_name)
        if chain is None:
            # 该档位此节点无配置，回退 T0 云端链
            chain = node.get("fallback_chain", {}).get("T0", [])
        # 从当前可用显存选起始级别：挑第一个满足 vram 的实现
        start_lv = 0
        for i, impl in enumerate(chain):
            need = float(impl.get("estimated_vram_need_gb", 0) or 0)
            if need == 0 or free_vram_gb >= need:
                start_lv = i
                break
            start_lv = i
        primary = chain[start_lv]
        nodes.append({
            "id": node["id"],
            "name": node.get("name", node["id"]),
            "primary": primary,
            "fallback_chain": chain,
            "params": primary.get("params", {}),
        })

    return {
        "tier": tier_name,
        "tier_label": matrix["tiers"][tier_name].get("label"),
        "free_vram_gb": free_vram_gb,
        "nodes": nodes,
        "note": "YAML 是数据不是代码；引擎按档位裁剪，运行时可再降级",
    }


def workflow_to_yaml(workflow: Dict[str, Any]) -> str:
    """序列化为 YAML 文本。"""
    if yaml is None:
        raise RuntimeError("缺少 PyYAML")
    return yaml.safe_dump(workflow, allow_unicode=True, sort_keys=False)


def generate_and_dump(tier: str, out_path: str,
                      matrix_path: str = MATRIX_PATH_DEFAULT,
                      free_vram_gb: float = 99.0) -> Dict[str, Any]:
    wf = generate_workflow(tier, matrix_path, free_vram_gb)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(workflow_to_yaml(wf))
    return wf
