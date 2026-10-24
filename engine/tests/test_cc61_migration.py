# -*- coding: utf-8 -*-
"""P0：固化 Pascal CC6.1 踩坑结论 + adaptive OOM 迁移串位（对应 commit 5b49b70）。

只用引擎侧已固化的真实逻辑做可回归的纯函数测试，不依赖 GPU/引擎实机产物：
1. advise_for_cell 建议字段完整
2. apply_advice_to_matrix 迁移前后节点数、分镜实现项总数不变（防串位/丢项）
3. 迁移后 fallback 链顺序满足"cloud 兜底提首、跑挂本地实现沉底"
"""
import copy
import sys
import os
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'engine', 'src'))
from picwf import adaptive


def _make_matrix():
    return {
        "nodes": [
            {
                "id": "node_a",
                "fallback_chain": {
                    "T1": [
                        {"impl": "local_fp16", "estimated_vram_need_gb": 8.0},
                        {"impl": "gguf_offload", "estimated_vram_need_gb": 4.0},
                        {"impl": "cloud_api", "estimated_vram_need_gb": None},
                    ]
                },
            }
        ]
    }


def _oom_cells(n=3):
    return [
        {"tier": "T1", "node_id": "node_a", "model_impl": "cc61_pascal",
         "peak_vram_gb": 9.5, "shot_elapsed_s": 15.0, "oom_degraded": True}
        for _ in range(n)
    ]


def _apply_advice_and_get_new_matrix():
    """apply_advice_to_matrix 返回深拷贝（原 dict 不污染），需取返回值而非原地引用"""
    matrix = _make_matrix()
    advice = {
        "T1::node_a::local_fp16": adaptive.advise_for_cell(_oom_cells())
    }
    new_matrix = adaptive.apply_advice_to_matrix(matrix, advice)
    return matrix, new_matrix


class TestCC61AdaptiveMigration:

    def test_advise_fields_complete(self):
        """踩坑结论固化：OOM 桶必须给出 est_vram/p95/oom_rate/recommend/migrate_reason 全字段"""
        adv = adaptive.advise_for_cell(_oom_cells())
        for field in ("samples", "est_vram", "oom_rate", "recommend_migrate", "migrate_reason"):
            assert field in adv, f"advise_for_cell 缺字段: {field}"
        assert adv["recommend_migrate"] is True
        assert adv["migrate_reason"] == "oom"

    def test_no_loss_no_shift(self):
        """迁移前后节点数、实现项总数严格不变（防串位/丢项）"""
        old_matrix, new_matrix = _apply_advice_and_get_new_matrix()
        before = [len(n["fallback_chain"]["T1"]) for n in old_matrix["nodes"]]
        after = [len(n["fallback_chain"]["T1"]) for n in new_matrix["nodes"]]
        assert before == after == [3], f"实现项数量变了: before={before} after={after}"
        assert len(new_matrix["nodes"]) == 1

    def test_migrate_ordering(self):
        """迁移后：cloud 类提到链首，跑挂的 local_fp16 沉底（亲民化兜底）"""
        _, new_matrix = _apply_advice_and_get_new_matrix()
        chain = new_matrix["nodes"][0]["fallback_chain"]["T1"]
        classes = [adaptive._impl_class(item["impl"]) for item in chain]
        assert classes[0] == "cloud", f"cloud 未提首: {classes}"
        assert chain[-1]["impl"] == "local_fp16", f"跑挂实现未沉底: {[c['impl'] for c in chain]}"

    @pytest.mark.skip(reason="依赖 1060 引擎真实产物（GPU 实机输出），CI 无此环境，人工本地冒烟")
    def test_cc61_real_engine_smoke(self):
        from picwf import adaptive
        import yaml
        # 本地有 GPU 时跑：加载真实 matrix.yaml 跑一遍 advise→apply 全链路
        matrix = yaml.safe_load(open(os.path.join(ROOT, "engine/config/matrix.yaml")))
        advice = {}
        adaptive.apply_advice_to_matrix(matrix, advice)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
