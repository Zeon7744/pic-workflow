# -*- coding: utf-8 -*-
"""爽点厂 HookForge Web UI：一键出片控制台。

用者友好图形界面：填剧本 + 选档位/画风/剧种/集数 → 调 pipeline_cli 出片 →
看执行进度 + 下载成片。普通创作者不用看底层命令。

启动：  python engine/ui/app.py  → http://127.0.0.1:8787
"""
import json
import os
import sys
import tempfile

# 让 UI 能 import picwf（engine/src 下）
_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

try:
    from flask import Flask, request, jsonify, send_from_directory, render_template, send_file
except Exception:
    # Flask 未装：给降级提示（不阻塞引擎其他部分）
    sys.exit("缺少 Flask，请先 pip install flask（Web UI 需要）；引擎核心不依赖 Flask")

from picwf import workflow_gen, pipeline_cli

app = Flask(__name__, template_folder="templates", static_folder="static")

# 下拉框选项（来自 matrix.yaml）
STYLE_OPTIONS = [
    ("S1_anime_jp", "日系动漫"), ("S2_korean_cool", "韩系冷感"),
    ("S3_cn_shuimo", "中国水墨"), ("S4_realistic", "写实"),
    ("S5_mmd_2d", "MMD二次元"), ("S6_shounen_manga", "少年漫画"),
    ("S7_shoujo_manga", "少女漫画"), ("S8_dark_gothic", "暗黑哥特"),
    ("S9_cyberpunk", "赛博朋克"), ("S10_steampunk", "蒸汽朋克"),
    ("S11_lowpoly", "低多边形"), ("S12_thick_paint", "厚涂"),
    ("S13_watercolor", "水彩"), ("S14_flat_illustration", "扁平插画"),
    ("S15_pixel_90s", "90s像素"), ("S16_film_photo", "胶片摄影"),
    ("S17_doc_real", "纪实写实"), ("S18_cel_3d", "卡通3D"),
    ("S19_ink_brush_cn", "国风水墨"), ("S20_photoreal_8k", "超写实8K"),
]
SCENARIO_OPTIONS = [
    ("light_comedy", "轻喜剧"), ("daily_romance", "日常恋爱"),
    ("male_revenge", "男频复仇"), ("dark_thriller", "暗黑惊悚"),
    ("fantasy_wuxia", "玄幻武侠"), ("romance_sad", "虐恋"),
    ("sci_fi_cyber", "科幻赛博"), ("action_battle", "动作打斗"),
    ("family_warm", "家庭温情"), ("school_youth", "校园青春"),
]
TIER_OPTIONS = [
    ("T0", "T0 · 无独显（纯云端出片，适合笔记本/轻薄本）"),
    ("T1", "T1 · 入门独显（1060/1650 级，6GB 显存，性价比之王）"),
    ("T2", "T2 · 中端独显（3060/4060 级，8-12GB）"),
]
_TIER_HUMAN = {k: v for k, v in TIER_OPTIONS}


@app.route("/")
def index():
    return render_template("index.html",
                           styles=STYLE_OPTIONS, scenarios=SCENARIO_OPTIONS,
                           tiers=TIER_OPTIONS, tier_human=_TIER_HUMAN)


@app.route("/api/options")
def options():
    return jsonify({"styles": STYLE_OPTIONS, "scenarios": SCENARIO_OPTIONS,
                    "tiers": TIER_OPTIONS})


@app.route("/api/run", methods=["POST"])
def run():
    """剧本+参数 → 出片。返回成片路径 + 执行报告。"""
    d = request.get_json(force=True, silent=True) or {}
    script_text = (d.get("script") or "").strip()
    if not script_text:
        return jsonify({"ok": False, "error": "剧本不能为空，请先粘贴剧本内容"}), 400
    tier = d.get("tier", "T1").upper()
    style = d.get("style", "S1_anime_jp")
    scenario = d.get("scenario", "dark_thriller")
    ep = int(d.get("ep", 10))
    free_vram = float(d.get("free_vram_gb", 6.0))
    audio_mode = d.get("audio_mode", "auto")

    # 剧本落临时文件（pipeline_cli 读路径）
    tmpd = tempfile.mkdtemp(prefix="hookforge_ui_")
    script_path = os.path.join(tmpd, "script.md")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_text)

    workdir = os.path.join(tmpd, "out")
    try:
        res = pipeline_cli.run(script_path, tier=tier, style=style,
                               scenario=scenario, ep=ep,
                               free_vram_gb=free_vram, audio_mode=audio_mode,
                               workdir=workdir)
    except Exception as e:
        return jsonify({"ok": False, "error": f"出片失败：{e}"}), 500

    final_video = res.get("final_video", "")
    video_exists = bool(final_video) and os.path.exists(final_video)
    return jsonify({
        "ok": res.get("ok", False),
        "final_video": final_video,
        "video_download": video_exists,
        "duration_s": res.get("artifacts", {}).get("package_publish", {}).get("duration_s", 0),
        "clip_count": res.get("artifacts", {}).get("post_assemble", {}).get("clip_count", 0),
        "order": res.get("order", []),
        "completed": res.get("completed", []),
        "failed": res.get("failed", {}),
        "report": res.get("report", ""),
    })


def _ui_tmp_prefix():
    """UI 临时工作目录前缀（跨平台）：以运行时 tempdir 为安全边界，防路径越权。"""
    import tempfile
    return os.path.join(tempfile.gettempdir(), "hookforge_ui_")


@app.route("/download/<path:name>")
def download(name):
    """只允许下载 UI 临时工作目录（tempdir/hookforge_ui_*）内的文件。
    name 形如 hookforge_ui_<id>/out/final.mp4，相对系统 tempdir 解析（跨平台一致）。"""
    import tempfile, re
    tdir = tempfile.gettempdir()
    norm = os.path.normpath(os.path.join(tdir, name))
    # 边界：必须落在 <tempdir>/hookforge_ui_* 内
    if not re.match(r"^" + re.escape(os.path.join(tdir, "hookforge_ui_")), norm):
        return jsonify({"ok": False, "error": "路径不合法"}), 400
    if not os.path.exists(norm):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    return send_file(norm, as_attachment=True,
                     download_name=os.path.basename(norm))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8787))
    print(f"爽点厂 HookForge Web UI 启动 → http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
