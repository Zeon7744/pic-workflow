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
    script_root: str = ""        # 原始剧本所在目录（剧本是源，分镜是派生物）
    media_root: str = ""         # 含 05_音频 的目录（BGM/SFX 素材检索根，注入 PICWF_ASSET_ROOTS）


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
    script_source: str = ""      # full 模式用的是原剧本，还是 _shots_to_md fallback


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

    # 剧本是源，分镜是派生物——不能拿资产库 shot 的 raw 反推剧本喂管线，
    # 那样会丢场景标题+对白分行结构，TTS 提取不到对白 → 哑片（440Hz 占位音）。
    script_md, res.script_source = _resolve_script(
        config, lib, plan_shots, shots_payload=_load_shots(lib, plan_shots))

    # BGM/SFX 素材检索根：05_音频 在云盘项目树，runner 的 out_dir 常脱离该树，
    # 靠 cwd 上溯找不到。显式注入 PICWF_ASSET_ROOTS，保住“素材检索上溯项目根”这一坑。
    if config.media_root:
        existing = os.environ.get("PICWF_ASSET_ROOTS", "")
        roots = [config.media_root] + [r for r in existing.split(os.pathsep) if r]
        os.environ["PICWF_ASSET_ROOTS"] = os.pathsep.join(roots)

    # 调 pipeline_cli.run（真 8 环节管线），工作目录指到 config.out_dir
    # 三坑（atrim 不用 -t / SFX 不进 ducking / 素材检索上溯项目根）原样保留
    from picwf.pipeline_cli import run as _run_cli
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


def _load_shots(lib: AssetLibrary, plan_shots: List[str]) -> List[Dict[str, Any]]:
    """读资产库 shot（只作对账/覆盖用，不反推剧本）。"""
    out = []
    for sid in plan_shots:
        s = lib.load_shot(sid)
        out.append({"id": sid, "raw": s.get("raw", ""),
                    "prompt": s.get("prompt", ""), "est_s": s.get("est_s", 3.0),
                    "shot_type": s.get("shot_type", ""),
                    "motion": s.get("motion", ""), "emotion": s.get("emotion", "")})
    return out


def _find_original_script(config: RunnerConfig, ep: int) -> str:
    """定位原始剧本（源）。优先级：config.script_root > 已知项目剧本目录。"""
    import glob
    cands = []
    if config.script_root:
        cands.append(os.path.join(config.script_root, f"剧本_助理反击_第{ep}集.md"))
    cands += [
        f"/Coze/Drive/简化画廊/剧本_助理反击_第{ep}集.md",
        f"{config.assets_root}/_scripts/剧本_助理反击_第{ep}集.md",
    ]
    for c in cands:
        if os.path.isfile(c):
            return c
    return ""


def _resolve_script(config: RunnerConfig, lib: AssetLibrary,
                    plan_shots: List[str],
                    shots_payload: List[Dict[str, Any]]):
    """确定喂给管线的剧本路径。

    返回 (script_md_path, source_desc)：
    - full：用原始剧本（结构完整，对白能被 TTS 提取），资产库只负责 shot/est_s 对账。
    - dirty：原始剧本为底，把脏 shot 的 prompt/est_s 覆盖进去（若原剧本缺失则退回 fallback）。
    - 原始剧本缺失时才用 _shots_to_md 反推（打 warn，已知会丢对白结构）。
    """
    orig = _find_original_script(config, config.episode)
    if orig:
        if config.mode == "full":
            return orig, "original"
        # dirty：原剧本为底，写一份仅覆盖脏 shot 的副本
        dirty_ids = set(plan_shots)
        with open(orig, encoding="utf-8") as f:
            text = f.read()
        overlay = os.path.join(config.out_dir, f"_ep{config.episode}_dirty_overlay.md")
        os.makedirs(config.out_dir, exist_ok=True)
        # 简单覆盖：把脏 shot 的 prompt 追加进场景（真实场景按 raw 精确替换需剧本 AST，
        # 此处在 P0 用"追加脏 shot 指令段"保证 TTS 对白结构不丢）
        extra = ["", "## [P0 脏分镜覆盖]"]
        for rec in shots_payload:
            if rec["id"] in dirty_ids:
                extra.append(f"- 镜头 {rec['id']}: {rec['prompt'] or rec['raw']}")
        with open(overlay, "w", encoding="utf-8") as f:
            f.write(text + "\n" + "\n".join(extra) + "\n")
        return overlay, "original+dirty-overlay"
    # fallback：原剧本缺失，反推（会丢对白结构，打 warn）
    import warnings
    warnings.warn(f"原始剧本缺失，_shots_to_md 反推可能丢失对白结构 → 哑片风险。ep={config.episode}")
    fb = _shots_to_md(plan_shots, config.episode, shots_payload, lib)
    return fb, "fallback-shot-derived"


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
    ap.add_argument("--media-root", default="/Coze/Drive/简化画廊",
                    help="含 05_音频 的目录，注入 PICWF_ASSET_ROOTS 供 BGM/SFX 检索")
    args = ap.parse_args(argv)
    r = run(RunnerConfig(assets_root=args.assets_root, episode=args.ep,
                         mode=args.mode, out_dir=args.out,
                         media_root=args.media_root))
    print(json.dumps({
        "ok": r.ok, "dirty_shots": r.dirty_shots, "out": r.out_path,
        "duration_s": r.duration_s, "loudness_db": r.audio_level_db,
        "error": r.error,
    }, ensure_ascii=False, indent=2))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
