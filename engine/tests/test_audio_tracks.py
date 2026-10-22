import yaml, pytest
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "src"))
from picwf.workflow_gen import generate_workflow
from picwf.conflict_check import check_conflict

MATRIX = str(pathlib.Path(__file__).parent.parent.parent / "config" / "matrix.yaml")

def test_dim_counts():
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    assert len(m["style_tracks"]) == 20
    assert len(m["music_tracks"]) == 30
    assert len(m["voice_tracks"]) == 30
    assert len(m["bgm_tracks"]) == 50

def test_four_dim_generates_nodes():
    b = generate_workflow(tier="T1", style="S13_watercolor", music="M25_classical_piano",
                          voice="V5_female_young_clear", bgm="B11_lyric_soft", free_vram_gb=4.9)
    ids = [n["id"] for n in b["nodes"]]
    assert "music" in ids and "voice" in ids and "bgm" in ids
    assert b["music"] == "M25_classical_piano"
    assert "conflict_warnings" not in b or not b.get("conflict_warnings")

def test_conflict_detection():
    hits = check_conflict("S18_cel_3d", music="M11_horror_drone", bgm="B09_horror_deep")
    assert len(hits) >= 1
    combos = [h["combo"] for h in hits]
    assert any("M11_horror_drone" in c for c in combos)

def test_no_audio_when_empty():
    b = generate_workflow(tier="T1", style="S1_anime_jp", free_vram_gb=4.9)
    ids = [n["id"] for n in b["nodes"]]
    assert "music" not in ids and "voice" not in ids and "bgm" not in ids

def test_style_20_keys():
    m = yaml.safe_load(open(MATRIX, encoding="utf-8"))
    for k in m["style_tracks"]:
        assert k.startswith("S"), k
    m2 = list(m["style_tracks"].keys())
    assert m2[0] == "S1_anime_jp" and m2[-1].startswith("S20")
