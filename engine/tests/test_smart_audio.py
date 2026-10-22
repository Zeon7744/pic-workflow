"""测试智能音频裁剪 + 四维协同优化 + 冲突检测 v2 + workflow_gen 新参数。"""
import yaml, pytest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))
from picwf.workflow_gen import generate_workflow
from picwf.audio_advisor import advise_tracks
from picwf.combo_optimizer import optimize
from picwf.conflict_check import check_conflict

MATRIX = str(pathlib.Path(__file__).parent.parent / "config" / "matrix.yaml")

def test_scenario_blocks_exist():
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    assert len(m["scenario_resource_map"]) >= 10
    assert len(m["emotion_arc_map"]) >= 5

def test_audio_advisor_auto_trims():
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    # 轻喜剧 auto 只 1 条
    assert [t["id"] for t in advise_tracks("light_comedy", m, "auto", 3)] == ["bgm"]
    # 男频逆袭 auto 2 条
    assert set(t["id"] for t in advise_tracks("male_revenge", m, "auto", 8)) == {"bgm", "music"}
    # full 3 条
    assert len(advise_tracks("light_comedy", m, "full", 3)) == 3

def test_combo_optimizer_scores():
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    r = optimize("male_revenge", 9, m)
    assert r["best"].get("music") == "M4_rock_electric"
    assert r["scores"]["best_score"] >= 50
    assert r["reason"].startswith("episode=9")

def test_conflict_check_v2_with_score():
    hits = check_conflict("S18_cel_3d", music="M11_horror_drone", bgm="B09_horror_deep")
    assert len(hits) >= 1
    for h in hits:
        assert "score" in h and "level" in h
        assert h["level"] in ("mid", "low")

def test_workflow_gen_new_params():
    # 新调用（scenario + ep + audio_mode）
    b = generate_workflow(tier="T1", style="S1_anime_jp", scenario="light_comedy",
                          ep=3, audio_mode="auto", free_vram_gb=4.9)
    ids = [n["id"] for n in b["nodes"] if n["id"] in ("music", "voice", "bgm")]
    assert ids == ["bgm"]  # 轻喜剧 auto 只 1 条
    assert b.get("audio_advised") == ["bgm"]
    assert b.get("combo_best")  # 优化器补了
    # 旧调用兼容（不传 scenario/ep，直接传 music/voice/bgm）
    b2 = generate_workflow(tier="T1", style="S1_anime_jp",
                           music="M25_classical_piano", voice="V5_female_young_clear",
                           bgm="B11_lyric_soft", free_vram_gb=4.9)
    ids2 = [n["id"] for n in b2["nodes"] if n["id"] in ("music", "voice", "bgm")]
    assert sorted(ids2) == ["bgm", "music", "voice"]
