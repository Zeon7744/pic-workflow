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
from picwf import i18n

app = Flask(__name__, template_folder="templates", static_folder="static")

# 下拉框选项（来自 matrix.yaml）
# 下拉框选项来自 i18n（中英双语，跟随 locale）
def _style_opts():
    return i18n.style_options()
def _scenario_opts():
    return i18n.scenario_options()
def _tier_opts():
    return i18n.tier_options()


@app.route("/")
def index():
    loc = request.args.get("lang", i18n.get_locale())
    i18n.set_locale(loc)
    return render_template("index.html",
                           styles=i18n.style_options(),
                           scenarios=i18n.scenario_options(),
                           tiers=i18n.tier_options(),
                           tier_human=dict(i18n.tier_options()),
                           locale=i18n.get_locale(),
                           all_text=i18n.all_ui_text(),
                           l10n_js=i18n.l10n_js())


@app.route("/api/options")
def options():
    loc = request.args.get("lang", i18n.get_locale())
    i18n.set_locale(loc)
    return jsonify(i18n.all_options())


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
