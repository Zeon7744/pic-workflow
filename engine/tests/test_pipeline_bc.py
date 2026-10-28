# -*- coding: utf-8 -*-
"""B 块（专业分镜拆解）+ C 块（CLI 端到端出片）回归。"""
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from picwf.pipeline_runner import script_to_shots
from picwf import pipeline_cli


def test_script_to_shots_professional_prompt():
    out = script_to_shots("第1场：男主进屋看到刀\n第2场：反转真相", shots_per_ep=10)
    assert out["mode"] in ("rules", "llm")
    # 每镜头有专业 prompt（景别+运动+情绪）
    for s in out["shots"]:
        assert s["prompt"], "prompt 不应为空"
        assert s["shot_type"] in ("特写", "近景", "中景", "全景")
    # 反转命中
    assert any(s["emotion"] == "反转" for s in out["shots"][:2])


def test_script_to_shots_skip_md_header():
    out = script_to_shots("# 江城情缘\n第1场：男主进屋\n第2场：对峙", shots_per_ep=10)
    # markdown 标题 # 开头的不进 shots
    assert not any(s["raw"].startswith("#") for s in out["shots"])
    assert out["shots"][0]["raw"].startswith("第1场")


def test_script_to_shots_llm_mode():
    llm = [{"text": "男主进屋", "prompt": "特写（缓推）男主进屋"}]
    out = script_to_shots("x", shots_per_ep=10, use_llm=True, llm_fn=lambda t: llm)
    assert out["mode"] == "llm"
    assert out["shots"][0]["prompt"] == "特写（缓推）男主进屋"


def test_cli_end_to_end(tmp_path):
    script = tmp_path / "script.md"
    script.write_text("# 江城情缘\n第1场：男主进屋\n第2场：反转真相", encoding="utf-8")
    out_dir = tmp_path / "out"
    res = pipeline_cli.run(str(script), tier="T1", scenario="dark_thriller",
                          ep=5, workdir=str(out_dir))
    assert res["ok"] is True
    assert res["final_video"], "成片路径不应为空"
    assert res["report"]
    # 报告已落盘
    import json
    r = json.load(open(res["report"], encoding="utf-8"))
    assert r["artifacts"]["package_publish"]["publish_ready"] is True
    assert len(r["completed"]) == len(r["order"])


def test_cli_resume(tmp_path):
    script = tmp_path / "script.md"
    script.write_text("第1场：男主进屋\n第2场：对峙", encoding="utf-8")
    out_dir = tmp_path / "out2"
    res = pipeline_cli.run(str(script), tier="T1", ep=5,
                           workdir=str(out_dir),
                           resume_ids=["script_struct", "character_image"])
    assert "script_struct" in res["skipped"]
    assert res["ok"] is True

def test_cli_exposes_mode_and_delivery_report(tmp_path):
    script = tmp_path / "script.md"
    script.write_text("# 江城情缘\n第1场：男主进屋\n第2场：反转真相", encoding="utf-8")
    out_dir = tmp_path / "out_mode"
    res = pipeline_cli.run(str(script), tier="T1", scenario="dark_thriller",
                           ep=3, workdir=str(out_dir), mode="pro")
    # 语义变更：mock 画面不算"可交付"，只算"可预览"。
    # 流程必须跑通(preview_ready)，但内容等级须诚实标注为 preview。
    dr = res["delivery_readiness"]
    assert dr["preview_ready"] is True, dr["gaps"]
    assert dr["content_grade"] == "preview", dr["content_grade"]
    assert dr["ready"] is False, "mock 画面不得判为可交付"
    assert any("占位" in g for g in dr["gaps"]), dr["gaps"]
    import json
    report = json.load(open(res["report"], encoding="utf-8"))
    assert report["mode"] == "pro"
    assert report["mode_overlay"]["mode_label"] == "进阶"
    assert report["mode_feedback"]["mode"] == "pro"
    assert report["delivery_readiness"]["checks"]["mode_feedback_visible"] is True

def test_cli_end_to_end_delivery_gaps_are_structured(tmp_path):
    script = tmp_path / "script.md"
    script.write_text("第1场：男主进屋", encoding="utf-8")
    out_dir = tmp_path / "out_gaps"
    res = pipeline_cli.run(str(script), tier="T1", ep=2, workdir=str(out_dir))
    dr = res["delivery_readiness"]
    assert "checks" in dr and "gaps" in dr
    assert isinstance(dr["ready"], bool)

def test_auto_repair_closes_mode_feedback_gap(tmp_path):
    """模式回流缺口可被自动修复：修复后 video_shot 带上 mode_feedback。"""
    import importlib
    ar = importlib.import_module("picwf.auto_repair")
    res = {"ok": True, "order": ["video_shot"],
           "completed": ["video_shot"], "failed": {},
           "artifacts": {"video_shot": {"clip_count": 1,
                                         "video_clips": [{"index": 1, "clip": True}]}}}
    wf = {"mode": "pro", "mode_overlay": {"mode": "pro", "params": {"resolution": 720}}}
    actions = []
    ar._inject_mode_feedback(res, wf, actions, 1)
    # 回流字段被自动补
    assert "mode_feedback" in res["artifacts"]["video_shot"]
    assert res["artifacts"]["video_shot"]["mode_feedback"]["mode"] == "pro"
    assert any(a.get("action") == "inject_mode_feedback" for a in actions)


def test_auto_repair_reports_unresolvable_model_runs():
    """不可自动修复的缺口（需真实模型）如实标注，不伪造成功。"""
    import importlib
    ar = importlib.import_module("picwf.auto_repair")
    res = {"ok": True, "order": ["video_shot"],
           "completed": ["video_shot"], "failed": {},
           "artifacts": {"video_shot": {"clip_count": 0,
                                         "mode_feedback": {"mode": "beginner"}}}}
    wf = {"mode": "beginner", "mode_overlay": {"mode": "beginner"}}
    repair = ar.repair_delivery(res, wf, {}, "/tmp/arx", max_rounds=1)
    # 视频未产生真实产物属需实跑项，应进入 unresolvable
    assert any("真实产物" in u or "真实模型" in u for u in repair["unresolvable"])


def test_cli_auto_repair_populated_and_persisted(tmp_path):
    """CLI 主链路默认开启自动修复，报告里含 auto_repair 字段。"""
    script = tmp_path / "s.md"
    script.write_text("# 江城\n第1场：男主进屋\n第2场：反转", encoding="utf-8")
    out = tmp_path / "out_ar"
    res = pipeline_cli.run(str(script), tier="T1", ep=3,
                           workdir=str(out), mode="pro", auto_repair=True)
    assert "auto_repair" in res, "CLI 应默认产出 auto_repair 块"
    ar = res["auto_repair"]
    assert "ready" in ar and "actions" in ar
    import json
    rpt = json.load(open(res["report"], encoding="utf-8"))
    assert "auto_repair" in rpt
    assert rpt["auto_repair"]["rounds"] >= 1


def test_cli_can_disable_auto_repair(tmp_path):
    script = tmp_path / "s2.md"
    script.write_text("第1场：男主进屋", encoding="utf-8")
    out = tmp_path / "out_no_ar"
    res = pipeline_cli.run(str(script), tier="T1", ep=2,
                           workdir=str(out), auto_repair=False)
    # 关闭时报告仍保留交付体检，但不写 auto_repair 动作块
    assert "auto_repair" not in res


def test_local_models_dir_injects_real_checkpoint_into_runner(tmp_path, monkeypatch):
    """本地模型目录有真实 checkpoint 时，runner 应索引到并注入 prompt。

    强制 mock 路径（隔离 ComfyUI 服务），只验证"本地模型 → prompt 注入"逻辑。
    """
    from picwf import comfyui_runner as cr
    from picwf.comfyui_runner import make_comfyui_runner
    monkeypatch.setattr(cr, "detect_comfyui_service",
                       lambda *a, **k: {"available": False, "url": "x",
                                        "gpu": {}, "error": "offline"})
    models_dir = tmp_path / "checkpoints"
    models_dir.mkdir()
    (models_dir / "sdxl_base.safetensors").write_text("dummy")
    runner = make_comfyui_runner(mock_fallback=True, workdir=str(tmp_path),
                                 local_models_dir=str(models_dir))
    assert len(runner.local_models) >= 1, "应索引到本地 checkpoint"
    out = runner.exec("shot_test_1", model_impl="sdxl_base")
    assert out.get("local_checkpoint") == "sdxl_base.safetensors", "prompt 应注入本地 checkpoint 名"
    assert out.get("local_models_dir") == str(models_dir)


def test_local_models_dir_missing_falls_back_cleanly(tmp_path, monkeypatch):
    """本地目录不存在时，索引为空、不报错，prompt 回退默认 checkpoint。"""
    from picwf import comfyui_runner as cr
    from picwf.comfyui_runner import make_comfyui_runner, DEFAULT_CHECKPOINT
    monkeypatch.setattr(cr, "detect_comfyui_service",
                       lambda *a, **k: {"available": False, "url": "x",
                                        "gpu": {}, "error": "offline"})
    runner = make_comfyui_runner(mock_fallback=True, workdir=str(tmp_path),
                                 local_models_dir=str(tmp_path / "not_exist_dir"))
    assert runner.local_models == {}, "目录不存在应索引为空"
    out = runner.exec("shot_test_1", model_impl="wan13b")
    # 无本地模型时回退 ComfyUI 默认 SD1.5 基础 checkpoint
    assert out.get("local_checkpoint") == DEFAULT_CHECKPOINT, "无本地模型应回退默认 checkpoint"


def test_auto_repair_downgrades_unresolvable_when_local_checkpoint(tmp_path):
    """本地有 checkpoint 时，真实产物类 unresolvable 应降级为可本地真跑。"""
    from picwf import auto_repair as ar
    res = {"ok": True, "order": ["video_shot"], "completed": ["video_shot"],
           "failed": {}, "artifacts": {"video_shot": {"clip_count": 0}}}
    wf = {"local_models": ["sdxl_base.safetensors"],
          "local_models_dir": "D:\\ComfyUI\\models"}
    actions = []
    kept = ar._local_downgrade(["视频镜头未产生真实产物，只能作为流程预演交付"],
                               res, wf, actions, 1)
    # 真实产物缺口被本地降级，unresolvable 不再保留
    assert "视频镜头未产生真实产物" not in " ".join(kept)
    video = res["artifacts"]["video_shot"]
    assert video.get("local_runnable") is True
    assert video.get("local_checkpoint") == "sdxl_base.safetensors"
    assert any(a.get("action") == "local_downgrade" for a in actions)


def test_auto_repair_keeps_unresolvable_when_no_local_model(tmp_path):
    """本地无 checkpoint 时，unresolvable 原样保留，不误降级。"""
    from picwf import auto_repair as ar
    res = {"ok": True, "artifacts": {"video_shot": {"clip_count": 0}}}
    wf = {"local_models": [], "local_models_dir": ""}
    actions = []
    kept = ar._local_downgrade(["视频镜头未产生真实产物，只能作为流程预演交付"],
                               res, wf, actions, 1)
    assert "视频镜头未产生真实产物" in " ".join(kept), "无本地模型应保留 unresolvable"
