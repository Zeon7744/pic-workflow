# -*- coding: utf-8 -*-
"""matrix 0.3.0 新增维度的结构与交叉引用测试。

覆盖：
- 四个新维度规模（镜型/平台/钩子/节奏）
- 与代码侧常量一致（platform_spec / hook_engine / narrative_architect / shot_choreo）
- 交叉引用不悬空（平台→节奏档、节奏档→BGM/画风/钩子、镜型→节拍）
- 编号连续性
- validator 对新维度 0 error 0 warning，且能拦下悬空引用
"""
import io
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from picwf import config_validator  # noqa: E402
from picwf import hook_engine, narrative_architect, platform_spec, shot_choreo  # noqa: E402

MATRIX = REPO / "config" / "matrix.yaml"

ALL_HOOK_TAGS = set()
for _v in hook_engine.SUITED_TAGS.values():
    ALL_HOOK_TAGS.update(_v)


def _load():
    with io.open(MATRIX, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_matrix_version_is_030():
    m = _load()
    assert m["version"] == "0.3.0"


def test_new_dimension_sizes():
    """matrix 0.3.0 规划值：24 镜型 / 8 平台 / 16 钩子 / 10 节奏档。"""
    m = _load()
    assert len(m["shot_patterns"]) == 24
    assert len(m["platform_profiles"]) == 8
    assert len(m["hook_patterns"]) == 16
    assert len(m["pace_profiles"]) == 10


def test_shot_pattern_numbering_continuous():
    m = _load()
    nums = []
    for k in m["shot_patterns"]:
        mt = re.match(r"^SP(\d+)_", k)
        assert mt, k
        nums.append(int(mt.group(1)))
    assert nums == list(range(1, 25)), nums


def test_pace_profile_numbering_continuous():
    m = _load()
    nums = []
    for k in m["pace_profiles"]:
        mt = re.match(r"^PC(\d+)_", k)
        assert mt, k
        nums.append(int(mt.group(1)))
    assert nums == list(range(1, 11)), nums


def test_shot_patterns_fields_complete():
    m = _load()
    for k, v in m["shot_patterns"].items():
        assert v.get("label"), k
        assert v.get("shot_size"), k
        assert v.get("camera_move"), k
        assert isinstance(v.get("est_s"), (int, float)) and v["est_s"] > 0, k
        assert isinstance(v.get("intensity"), int) and 1 <= v["intensity"] <= 5, k
        assert v.get("beats"), k
        assert v.get("note"), k


def test_shot_pattern_camera_move_in_choreo_vocabulary():
    """镜型的运镜取值必须落在 shot_choreo 的运镜词表内，否则排镜时无法执行。"""
    m = _load()
    vocab = set(shot_choreo._MOTION_SINGLE)
    for k, v in m["shot_patterns"].items():
        assert v["camera_move"] in vocab, "%s: %s not in %s" % (
            k, v["camera_move"], sorted(vocab))


def test_shot_pattern_beats_are_valid_beat_roles():
    m = _load()
    for k, v in m["shot_patterns"].items():
        for b in v["beats"]:
            assert b in narrative_architect.BEAT_ROLES, "%s: %s" % (k, b)


def test_platform_profiles_match_code_specs():
    """矩阵里的平台档案必须与 platform_spec.PLATFORM_SPECS 一一对应。"""
    m = _load()
    assert set(m["platform_profiles"]) == set(platform_spec.PLATFORM_SPECS)


def test_platform_profile_core_fields_match_spec():
    """矩阵与代码侧的时长/画幅/帧率必须一致，避免两处漂移。"""
    m = _load()
    for key, prof in m["platform_profiles"].items():
        spec = platform_spec.PLATFORM_SPECS[key]
        assert prof["aspect_ratio"] == spec["aspect_ratio"], key
        assert prof["fps"] == spec["fps"], key
        assert prof["min_duration_s"] == spec["min_duration_s"], key
        assert prof["max_duration_s"] == spec["max_duration_s"], key


def test_platform_profiles_cover_all_hooks():
    """每个平台至少声明一个钩子类型，且都必须是已知钩子。"""
    m = _load()
    for key, prof in m["platform_profiles"].items():
        hooks = prof.get("primary_hooks") or []
        assert hooks, key
        for h in hooks:
            assert h in hook_engine.HOOK_CATALOG, "%s: %s" % (key, h)
        tags = prof.get("platform_tags") or []
        assert tags, key
        for t in tags:
            assert t in ALL_HOOK_TAGS, "%s tag %s" % (key, t)


def test_hook_patterns_match_code_catalog():
    m = _load()
    assert set(m["hook_patterns"]) == set(hook_engine.HOOK_CATALOG)


def test_hook_pattern_beat_valid():
    m = _load()
    for k, v in m["hook_patterns"].items():
        assert v["beat"] in narrative_architect.BEAT_ROLES, k


def test_hook_pattern_has_dual_layer_directives():
    """钩子必须同时有 3 秒钩子与 15 秒钩子两层指令。"""
    m = _load()
    for k, v in m["hook_patterns"].items():
        assert v.get("hook_3s"), k
        assert v.get("hook_15s"), k
        assert v.get("emotion"), k
        assert v.get("promise"), k
        assert v.get("desc"), k


def test_pace_profiles_cross_refs_resolve():
    m = _load()
    for k, v in m["pace_profiles"].items():
        assert v["bgm_pref"] in m["bgm_tracks"], "%s bgm_pref" % k
        assert v["style_pref"] in m["style_tracks"], "%s style_pref" % k
        for h in v.get("hook_types") or []:
            assert h in m["hook_patterns"], "%s hook_types" % k
        for s in v.get("shot_patterns") or []:
            assert s in m["shot_patterns"], "%s shot_patterns" % k


def test_every_platform_has_a_3s_hook():
    """3 秒钩子铁律：每个平台至少一个 3 秒内能爆发的钩子。"""
    m = _load()
    for key, prof in m["platform_profiles"].items():
        quick = [h for h in prof["primary_hooks"]
                 if m["hook_patterns"][h]["deadline_s"] <= 3]
        assert quick, "%s 没有 3 秒内钩子" % key


def test_platform_profile_pace_profile_resolves():
    m = _load()
    for k, v in m["platform_profiles"].items():
        assert v["pace_profile"] in m["pace_profiles"], k


def test_pace_profile_scenarios_resolve():
    m = _load()
    for k, v in m["pace_profiles"].items():
        for s in v.get("scenarios") or []:
            assert s in m["scenario_resource_map"], "%s scenarios" % k


def test_pace_profile_payoff_density_matches_narrative_rules():
    """节奏档的爽点密度必须与叙事层规则同源（≥3 爽点 + 1 甜点）。"""
    m = _load()
    for k, v in m["pace_profiles"].items():
        assert v["payoff_per_ep"] >= 3, k
        assert v["sweet_per_ep"] >= 1, k


def test_validator_reports_zero_errors_and_warnings():
    """扩维后矩阵必须零 error 零 warning。"""
    m = _load()
    r = config_validator.validate_matrix(m)
    assert r["errors"] == [], r["errors"]
    assert r["warnings"] == [], r["warnings"]


def test_validator_catches_dangling_new_dim_refs():
    """新维度的悬空引用必须被校验器拦下。"""
    m = _load()
    m["platform_profiles"]["redfruit"]["pace_profile"] = "PC_does_not_exist"
    m["pace_profiles"]["PC1_slow_burn"]["bgm_pref"] = "B99_not_exist"
    m["pace_profiles"]["PC1_slow_burn"]["style_pref"] = "S99_not_exist"
    m["hook_patterns"]["conflict_open"]["beat"] = "not_a_beat"
    m["shot_patterns"]["SP1_extreme_closeup"]["beats"] = ["not_a_beat"]
    r = config_validator.validate_matrix(m)
    assert len(r["errors"]) >= 5, r["errors"]


def test_validator_catches_missing_label_in_track_dims():
    """音轨维度的 label 损坏必须被拦下（历史畸形 key 事故回归）。"""
    m = _load()
    m["voice_tracks"]["V1_male_young_cool"] = {}
    m["bgm_tracks"]["B01_battle_ramp"] = {}
    m["music_tracks"]["M1_pop_bright"] = {}
    r = config_validator.validate_matrix(m)
    assert len(r["errors"]) >= 3, r["errors"]


def test_track_dims_entries_are_wellformed():
    """音轨维度不得再出现 `label:"xxx"` 这类畸形 key。"""
    m = _load()
    bad_key = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*:"')
    for dim in ("music_tracks", "voice_tracks", "bgm_tracks"):
        for k, v in m[dim].items():
            assert isinstance(v, dict) and v, "%s.%s not a dict" % (dim, k)
            assert v.get("label"), "%s.%s missing label" % (dim, k)
            for kk in v:
                assert not bad_key.match(str(kk)), "%s.%s malformed key %r" % (dim, k, kk)


def test_track_dim_counts_stable():
    """既有维度规模不变（扩维不缩维）。"""
    m = _load()
    assert len(m["style_tracks"]) == 28
    assert len(m["music_tracks"]) == 30
    assert len(m["voice_tracks"]) == 48
    assert len(m["bgm_tracks"]) == 50
    assert len(m["scenario_resource_map"]) == 18
    assert len(m["emotion_arc_map"]) == 8
