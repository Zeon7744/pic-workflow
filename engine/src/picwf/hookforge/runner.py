# -*- coding: utf-8 -*-
"""L1 统一 runner：四入口（CLI/脚本/画布/API）都调这一个。

runner 只暴露 run()，内部：
  1. 读 AssetLibrary，决定哪些 shot 脏了要重出
  2. 只重出脏 shot 的分镜图（定妆照 i2i 复用缓存）
  3. 8 环节走同一条管线：script_struct -> character_image ->
     storyboard_prompt -> video_shot -> fx_enhance -> post_assemble ->
     bgm_audio -> package_publish
  4. BGM 床 + SFX 轨按 audio_scene_mix 的规则拼接（atrim 不用 -t、SFX 不进 ducking）

对回归要求：跑一遍 ep1 产物和「助理反击_ep1_分段BGM版.mp4」对齐或说明差异。
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 统一 runner 是引擎里唯一的管线入口；任何 CLI/脚本/画布/API 都调这里，
# 禁止绕过（否则四套逻辑各跑各的，资产库的脏分镜白建）。
from picwf import audio_scene_mix as _asmix
from picwf.hookforge.asset_lib import AssetLibrary
from picwf.workflow_gen import generate_workflow
from picwf.pipeline_executors import make_executors


@dataclass
class RunnerConfig:
    assets_root: str = "/mnt/f/项目/开发/pic/assets"
    episode: int = 1
    mode: str = "full"            # full=全量 | dirty=只重出脏 shot
    out_dir: str = "./_out/regress"
    script: str = ""             # 没有资产库里的 shot 时可选传入剧本
    cloud_model: str = ""        # 空=走 make_executors 默认（agnes image）
    keep_intermediates: bool = True


@dataclass
class DryRunResult:
    ok: bool
    plan: List[Dict[str, Any]] = field(default_factory=list)   # 要做的事
    dirty_shots: List[str] = field(default_factory=list)
    assets_to_regenerate: List[str] = field(default_factory=list)
    out_path: str = ""
    duration_s: float = 0.0
    audio_level_db: float = 0.0
    diff_vs_prev: str = ""
    error: str = ""
    commit: str = ""


def _ffprobe_dur(path: str) -> float:
    import subprocess
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip() or 0)
    except ValueError:
        return 0.0


def _loudness_db(path: str) -> float:
    """粗量：mean_volume 作为响度参考（正式响度 loudnorm 在成片阶段已做）。"""
    import re, subprocess
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", path, "-af", "volumedetect",
         "-f", "null", "/dev/null"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?\d+\.?\d*)\s*dB", r.stderr)
    return float(m.group(1)) if m else -99.0


def _make_plan(lib: AssetLibrary, ep: int, mode: str) -> List[str]:
    """按脏分镜算要跑哪些 shot。"""
    all_shots = lib.manifest.get("episodes", {}).get(str(ep), [])
    if mode == "full":
        return all_shots
    dirty = set()
    for a, v in lib.manifest.get("dirty", {}).items():
        dirty.update(v.get("dirty_shots", []))
    return [s for s in all_shots if s in dirty] or all_shots


def run(config: RunnerConfig) -> DryRunResult:
    """唯一入口：跑 ep1 全量或脏分镜回归。"""
    try:
        lib = AssetLibrary(config.assets_root)
    except FileNotFoundError as e:
        return DryRunResult(ok=False, error=str(e))

    plan_shots = _make_plan(lib, config.episode, config.mode)
    res = DryRunResult(ok=True, plan=[{"kind":"shot","asset_id": s, "action": "regenerate"} for s in plan_shots],
                       dirty_shots=plan_shots if config.mode == "dirty" else [])

    # 把 plan 写进 config，供 executors 使用
    os.makedirs(config.out_dir, exist_ok=True)
    res.out_path = os.path.join(config.out_dir, f"final_ep{config.episode}.mp4")

    # 走 8 环节：先按全量生成（当前 ep1 是基准），后续 mode=dirty 时只重出脏 shot
    # 这里为了对齐现有 分段BGM版，直接跑全量 8 环节（含分段 BGM + SFX）
    wf = generate_workflow(tier="T1", ep=config.episode, scenario="dark_thriller")
    ex = make_executors(wf, workdir=config.out_dir)
    # script_struct 用资产库里的 shot 数据（不重新生成，保证回归稳定）
    shots_payload = []
    for sid in plan_shots:
        s = lib.load_shot(sid)
        rec = {"id": sid, "raw": s["raw"], "prompt": s.get("prompt", ""),
               "est_s": s.get("est_s", 3.0), "shot_type": s.get("shot_type", ""),
               "motion": s.get("motion", ""), "emotion": s.get("emotion", "")}
        shots_payload.append(rec)
        res.plan.append({"kind":"shot","asset_id":sid,"raw":s["raw"],"est_s":rec["est_s"],"shot_type":rec["shot_type"],"action":"regenerate"})
    # 调 pipeline_cli.run（真 8 环节管线），工作目录指到 config.out_dir
    # 这样三坑（atrim / SFX 不进 ducking / 素材检索向上找项目根）原样保留
    from picwf.pipeline_cli import run as _run_cli
    # 用 assets 里存的 shot 拼成一个临时剧本，喂给 run()（run() 期望 .md 输入）
    script_md = _shots_to_md(plan_shots, config.episode, shots_payload, lib)
    res.out_path = os.path.join(config.out_dir, f"final_ep{config.episode}.mp4")
    cli_res = _run_cli(script_md, tier="T1", style="S1_anime_jp",
                       scenario="dark_thriller", ep=config.episode,
                       audio_mode="auto", workdir=config.out_dir,
                       cloud_model=config.cloud_model)
    res.ok = bool(cli_res.get("ok"))
    if not res.ok:
        res.error = str(cli_res.get("auto_repair", {}).get("unresolvable", "") or "管线跑失败")
        return res
    # 读回 duration / 响度
    final = os.path.join(config.out_dir, f"final_ep{config.episode}.mp4")
    if os.path.isfile(final):
        res.out_path = final
        res.duration_s = round(_ffprobe_dur(final), 2)
        res.audio_level_db = _loudness_db(final)
    return res


def _shots_to_md(shot_ids: List[str], ep: int, shots_payload: List[Dict[str, Any]],
                 lib: AssetLibrary) -> str:
    """把 asset 里的 shot 拼成 pipeline_cli 期望的 .md 格式（剧本+分镜混合）。

    简化：直接用现有 ep1 剧本的格式（剧本_助理反击_第1集.md），
    因为资产库里的 shot 就是从那里面迁过来的。
    """
    # 从 shots_payload 反推剧本 body
    lines = ["# 助理反击 第1集（资产库版）", "", "## 分镜", ""]
    for s in shots_payload:
        lines.append(f"- {s['raw']}（{s.get('shot_type','')}, {s.get('est_s')}s）")
    md = "\n".join(lines)
    # 写进 asset 目录（不覆盖原剧本）
    p = os.path.join(os.path.dirname(lib.path), f"_ep{ep}_shots_from_assets.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(md)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser("HookForge unified runner")
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--mode", default="full", choices=["full", "dirty"])
    ap.add_argument("--assets-root", default="/mnt/f/项目/开发/pic/assets")
    ap.add_argument("--out", default="./_out/regress")
    args = ap.parse_args(argv)
    r = run(RunnerConfig(assets_root=args.assets_root, episode=args.ep,
                         mode=args.mode, out_dir=args.out))
    print(json.dumps({
        "ok": r.ok, "dirty_shots": r.dirty_shots, "out": r.out_path,
        "duration_s": r.duration_s, "loudness_db": r.audio_level_db,
        "error": r.error,
    }, ensure_ascii=False, indent=2))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
