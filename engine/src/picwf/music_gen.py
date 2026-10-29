# -*- coding: utf-8 -*-
"""music_gen: 音乐轨生成（配合剧本产出该段该配的音乐）。

定位(白皇 2026-10-28 路径B): 不由引擎硬编码某家音乐 API，而是
  1) 先从 matrix 的 music_tracks / bgm_tracks 风格表，结合剧种/情绪弧线，
     推导出"这一段该配什么音乐"的**结构化规格**(双语描述 + bpm + 乐器 + mood)
  2) 再把规格交给可插拔后端去真生成

后端(与 voice_tts 同构):
  - suno_api: Suno 协议兼容端点(POST /api/music/create -> 轮询 /api/music/query)
              可指向 suno-api.io / musicapi.ai / 任意 Suno 代理
  - spec_only: 不真生成, 只返回规格。用于无 key 场景 —— 白皇可直接拿
               style_zh 到 sunoyinyue.com 手动生成(该站无公开 API, 属人工辅助路径)

接口(对齐 audio_advisor 的 impl="music_gen.<track_key>"):
  build_music_spec(track_key, matrix=None, duration_s=30, mood_hint="") -> spec dict
  generate(spec_or_key, backend="auto", out_path=None, ...) -> {"ok","path","backend","spec","error"}
  export_prompt_sheet(keys, out_path=None) -> 批量导出人工生成清单

环境变量:
  SUNO_API_BASE / SUNO_API_KEY / SUNO_MODEL
"""
import json
import os
import subprocess
import shutil

FFMPEG = shutil.which("ffmpeg")
import time
import urllib.request
from typing import Any, Dict, List, Optional

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

_MATRIX_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "matrix.yaml")

SUNO_BASE = os.environ.get("SUNO_API_BASE", "").rstrip("/")
SUNO_KEY = os.environ.get("SUNO_API_KEY", "")
SUNO_MODEL = os.environ.get("SUNO_MODEL", "suno-v6")

# 乐器 / mood 的中英映射：让 spec 同时能被 Suno(英文 tags) 和
# sunoyinyue.com(中文描述) 直接使用。未命中的词原样保留。
_ZH_EN = {
    "古琴": "guqin", "琵琶": "pipa", "笛": "flute", "古筝": "guzheng",
    "木吉他": "acoustic guitar", "口琴": "harmonica", "钢琴": "piano",
    "爵士鼓": "jazz drums", "贝斯": "bass", "合成器": "synth",
    "电吉他": "electric guitar", "鼓": "drums", "弦乐": "strings",
    "大提琴": "cello", "小提琴": "violin", "管风琴": "organ",
    "铜管": "brass", "竖琴": "harp", "电子鼓": "electronic drums",
    "808": "808 bass", "打击乐": "percussion",
    "治愈日常": "warm healing", "古雅": "elegant classical",
    "热血": "energetic", "紧张": "tense", "悲伤": "sad emotional",
    "温暖": "warm", "轻盈": "light airy", "史诗": "epic",
    "悬疑": "suspense", "恐怖": "eerie", "欢快": "cheerful",
    "浪漫": "romantic", "冷峻": "cold cinematic", "励志": "uplifting",
    "孤独": "lonely", "宏大": "grand", "轻快": "breezy",
    "抒情": "lyrical", "激昂": "rousing",
    "萨克斯": "saxophone", "低音提琴": "double bass", "中提琴": "viola",
    "长笛": "flute", "单簧管": "clarinet", "小号": "trumpet", "圆号": "horn",
    "手风琴": "accordion", "班卓琴": "banjo", "曼陀林": "mandolin",
    "电子音效": "sound design", "氛围铺垫": "ambient pad", "环境音": "ambience",
    "慵懒都市": "lazy urban", "动漫流行": "anime pop", "国风器乐": "chinese traditional",
    "爵士摇摆": "jazz swing", "民谣吉他": "folk guitar", "史诗管弦": "epic orchestral",
    "虐心": "heartbreaking", "离别": "farewell", "悲情": "tragic",
    "悬疑冷峻": "cold suspense", "恐怖深底": "deep horror", "搞笑放松": "comic relaxed",
    "日常轻快": "light daily", "战斗升级": "battle ramp", "追逐紧迫": "urgent chase",
    "高潮峰值": "climax peak", "反转": "plot twist", "告白": "confession",
    "过渡铺垫": "transitional", "压迫惊吓": "oppressive scare", "喜感调节": "comedic relief",
    "情感铺陈": "emotional build", "情感升温": "rising emotion", "悲伤催泪": "tearjerker",
    "紧张追戏": "tense pursuit", "对决高燃": "high-energy duel", "全剧高潮": "series climax",
    "悬念积累": "suspense build", "轻松": "relaxed", "高级感": "premium feel",
    "都市": "urban", "情感": "emotional", "校园": "school", "成长": "coming of age",
}


def _matrix(matrix=None, path=None):
    if matrix is not None:
        return matrix
    if yaml is None:
        raise RuntimeError("需要 pyyaml 解析 matrix.yaml")
    p = path or os.environ.get("MATRIX_PATH", "") or _MATRIX_DEFAULT
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# 分词符：乐器串常用 / 、 + + ，还有全角
_SEPS = ("/", "、", "+", "＋", "，", ",")


def _split_bits(text: str):
    s = str(text or "")
    for sep in _SEPS:
        s = s.replace(sep, "\x00")
    return [b.strip() for b in s.split("\x00") if b.strip()]


def _translate_bit(bit: str) -> str:
    """单段翻译：精确 -> 最长子串 -> 原文。"""
    if bit in _ZH_EN:
        return _ZH_EN[bit]
    # 子串命中取最长键（如 "热血青春" -> "热血"）
    hits = [k for k in _ZH_EN if k in bit]
    if hits:
        best = max(hits, key=len)
        return _ZH_EN[best]
    return bit


def _tr(text: str) -> str:
    """把中文乐器/mood 词尽量翻成英文，未命中保留原文。"""
    if not text:
        return ""
    return ", ".join(_translate_bit(b) for b in _split_bits(text))


def _pick_table(track_key: str, m: Dict[str, Any]) -> tuple:
    """track_key 前缀决定取哪张表：M* -> music_tracks, B* -> bgm_tracks。"""
    if track_key.startswith("B"):
        return "bgm_tracks", m.get("bgm_tracks", {}).get(track_key, {})
    return "music_tracks", m.get("music_tracks", {}).get(track_key, {})


def _resolve_music_ref(ref: str, m: Dict[str, Any]) -> Dict[str, Any]:
    """把 bgm_tracks 的 music_ref（如 "M4/M10") 解析成 music_tracks 的行。"""
    if not ref:
        return {}
    first = _split_bits(str(ref).split("/")[0])[0] if _split_bits(str(ref)) else ""
    first = str(ref).split("/")[0].strip()
    tracks = m.get("music_tracks", {})
    if first in tracks:
        return tracks[first]
    # 前缀匹配：M29 -> M29_xxx
    for k, v in tracks.items():
        if k == first or k.startswith(first + "_"):
            return v
    return {}


def build_music_spec(track_key: str, matrix=None, duration_s: int = 30,
                     mood_hint: str = "", scenes_hint: str = "",
                     path: Optional[str] = None) -> Dict[str, Any]:
    """构造音乐规格。track_key 可以是 M*/B* 或任意自定义 key。

    B* 类（bgm_tracks）常缺 bpm/instruments，会用其 music_ref 指向的
    music_tracks 行补齐，保证规格可直接投喂音乐模型。

    返回:
      {track_key, table, label, style_zh, style_en, tags, bpm, instruments,
       mood, scenes, duration_s, found}
    """
    m = _matrix(matrix, path)
    table, row = _pick_table(track_key, m)
    found = bool(row)

    # B 类补字段
    if table == "bgm_tracks" and row and not row.get("instruments"):
        ref_row = _resolve_music_ref(row.get("music_ref", ""), m)
        if ref_row:
            merged = dict(ref_row)
            merged.update({k: v for k, v in row.items() if v})
            # bgm 的 label/func/scene 优先，风格取 ref 的
            row = merged

    label = row.get("label", track_key)
    key_sig = row.get("key", "")
    bpm = row.get("bpm") or []
    instruments = row.get("instruments", "")
    mood = mood_hint or row.get("mood", "")
    scenes = scenes_hint or row.get("scenes") or row.get("scene", "") or row.get("func", "")

    inst_en = _tr(instruments)
    mood_en = _tr(mood)
    bpm_txt = ("%d-%d bpm" % (bpm[0], bpm[1])) if isinstance(bpm, list) and len(bpm) >= 2 else ""

    # 中文描述：给 sunoyinyue.com 这类中文站直接粘贴用
    zh_bits = []
    if label:
        zh_bits.append(label)
    if key_sig:
        zh_bits.append("调性" + str(key_sig))
    if instruments:
        zh_bits.append("乐器" + str(instruments))
    if mood:
        zh_bits.append("情绪" + str(mood))
    if scenes:
        zh_bits.append("适用" + str(scenes))
    if bpm_txt:
        zh_bits.append(bpm_txt)
    zh_bits.append("纯器乐无人声")
    style_zh = "，".join(zh_bits)

    # 英文描述：给 Suno API / 国际模型用
    en_bits = []
    if inst_en:
        en_bits.append(inst_en)
    if mood_en:
        en_bits.append(mood_en)
    if label:
        en_bits.append(_translate_bit(str(label)))
    if bpm_txt:
        en_bits.append(bpm_txt)
    en_bits.append("instrumental")
    # 去重保序（label 与 mood 可能译成同一个词）
    _seen = set()
    _uniq = []
    for b in en_bits:
        key = b.strip().lower()
        if key and key not in _seen:
            _seen.add(key)
            _uniq.append(b)
    style_en = ", ".join(_uniq)

    tags = [t for t in [mood_en, inst_en, "instrumental"] if t]

    return {
        "track_key": track_key,
        "table": table,
        "label": label,
        "style_zh": style_zh,
        "style_en": style_en,
        "tags": ", ".join(tags),
        "bpm": bpm,
        "instruments": instruments,
        "mood": mood,
        "scenes": scenes,
        "duration_s": int(duration_s),
        "found": found,
    }


def _provider_available(backend: str) -> bool:
    if backend == "suno_api":
        return bool(SUNO_KEY and SUNO_BASE)
    if backend == "spec_only":
        return True
    return False


def _post_json(url: str, payload: dict, key: str, timeout: int = 300) -> Any:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer %s" % key,
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url: str, out_path: str, timeout: int = 300) -> int:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        data = r.read()
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


def _do_suno(spec: Dict[str, Any], out_path: str, poll_timeout: int = 600) -> Dict[str, Any]:
    """Suno 协议：create -> 轮询 query -> 下载 audio_url。"""
    if not _provider_available("suno_api"):
        return {"ok": False, "path": "", "backend": "suno_api", "spec": spec,
                "duration_ms": 0,
                "error": "缺少 SUNO_API_BASE / SUNO_API_KEY"}
    try:
        created = _post_json("%s/api/music/create" % SUNO_BASE,
                             {"description": spec["style_en"],
                              "instrumental": True,
                              "model": SUNO_MODEL}, SUNO_KEY)
        if isinstance(created, dict):
            created = created.get("data") or created.get("results") or [created]
        song_ids = [t.get("song_id") for t in created if isinstance(t, dict) and t.get("song_id")]
        if not song_ids:
            return {"ok": False, "path": "", "backend": "suno_api", "spec": spec,
                    "duration_ms": 0, "error": "create 未返回 song_id: %s" % str(created)[:200]}

        deadline = time.time() + poll_timeout
        tracks = []
        while time.time() < deadline:
            time.sleep(10)
            tracks = _post_json("%s/api/music/query" % SUNO_BASE,
                                {"song_ids": song_ids, "model": SUNO_MODEL}, SUNO_KEY)
            if isinstance(tracks, dict):
                tracks = tracks.get("data") or tracks.get("results") or [tracks]
            done = [t for t in tracks if isinstance(t, dict)
                    and t.get("status") == "completed" and t.get("audio_url")]
            if done:
                audio_url = done[0]["audio_url"]
                size = _download(audio_url, out_path)
                return {"ok": True, "path": out_path, "backend": "suno_api",
                        "spec": spec, "duration_ms": spec["duration_s"] * 1000,
                        "audio_url": audio_url, "size": size, "error": ""}
        return {"ok": False, "path": "", "backend": "suno_api", "spec": spec,
                "duration_ms": 0, "error": "轮询超时(%ds)未完成" % poll_timeout}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "path": "", "backend": "suno_api", "spec": spec,
                "duration_ms": 0, "error": "%s: %s" % (type(e).__name__, e)}


# ---------------------------------------------------------------------------
# 本地素材模式（白皇 2026-10-28 定：SUNO key 没有，MiniMax 音乐端点已停用 410）
# 素材由平台侧 generate_music 产出、落进项目目录，管线只负责「循环/裁切到时长」，
# 本环节不调任何音乐生成 API。
# ---------------------------------------------------------------------------
_AUDIO_EXT = ("mp3", "wav", "m4a", "aac", "flac", "ogg")
# 素材落点，按优先级。平台侧只要把文件放进来，管线就能自动接上。
_ASSET_DIRS = ("", "assets", "music", "audio", "bgm", "素材", "音乐",
               # 红剑交付的资产目录：命名形如 bgm_悬疑压迫.mp3 / 特效音/sfx_冲击_打脸.mp3
               "05_音频", "05_音频/bgm", "05_音频/特效音", "05_音频/音乐")


_DELIVERY_DIRS = ("05_音频", "05_音频/bgm", "05_音频/特效音", "05_音频/音乐")


def _extra_asset_roots():
    """交付目录可能和 workdir 不在同一棵树（资产通常落项目根的 05_音频/）。

    优先级：PICWF_ASSET_ROOTS（冒号分隔，显式指定）> 当前工作目录。
    不硬编码项目路径：换项目/换机器时会读到别的工程的素材。
    """
    roots = []
    env = os.environ.get("PICWF_ASSET_ROOTS", "")
    for r in env.split(os.pathsep):
        if r.strip():
            roots.append(r.strip())
    roots.append(os.getcwd())
    out = []
    for r in roots:
        if os.path.isdir(r) and r not in out:
            out.append(r)
    return out


def find_asset_by_keyword(workdir: str, keywords, subdirs=None,
                          min_size=1024, up_levels=3) -> str:
    """按关键词模糊找本地音频素材，返回文件名最短的匹配。

    平台侧命名不固定（bgm_悬疑压迫.mp3 / BGM-悬疑-压迫.mp3 都出现过），
    精确名匹配不到时用这个兜底：文件名同时含全部关键词即命中。
    交付目录 05_音频/ 常在 workdir 的上级（项目根），所以会向上找几层。
    """
    if not workdir:
        return ""
    kws = [str(k) for k in (keywords or []) if k]
    if not kws:
        return ""
    bases = []
    seen = set()
    cur = os.path.abspath(workdir)
    for _ in range(up_levels + 1):
        for d in (subdirs if subdirs is not None else _ASSET_DIRS):
            p = os.path.join(cur, d) if d else cur
            if p not in seen and os.path.isdir(p):
                seen.add(p)
                bases.append(p)
        for d in _DELIVERY_DIRS:
            p = os.path.join(cur, d)
            if p not in seen and os.path.isdir(p):
                seen.add(p)
                bases.append(p)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # workdir 的上级树里没有，再看显式指定的交付根
    for root in _extra_asset_roots():
        if root in seen:
            continue
        seen.add(root)
        for d in ("",) + _DELIVERY_DIRS:
            p = os.path.join(root, d) if d else root
            if p not in seen and os.path.isdir(p):
                seen.add(p)
                bases.append(p)
    hits = []
    for base in bases:
        try:
            files = os.listdir(base)
        except OSError:
            continue
        for fn in files:
            stem, ext = os.path.splitext(fn)
            if ext.lower().lstrip(".") not in _AUDIO_EXT:
                continue
            if not all(k in stem for k in kws):
                continue
            p = os.path.join(base, fn)
            try:
                if os.path.getsize(p) <= min_size:
                    continue
            except OSError:
                continue
            hits.append((len(fn), p))
    if not hits:
        return ""
    return sorted(hits)[0][1]


# ---------------------------------------------------------------------------
# 主题曲（红剑 2026-10-29 定版）
# 管线只认「主用版 / 片尾版」两个稳定名；原始母版名留作向后兼容兜底。
# 只在 05_音频/ 根找：试听摘要/ 下是弃用的 _preview 剪辑，进管线会拿到 10s 片段。
# ---------------------------------------------------------------------------
THEME_NAMES = {
    "main": ("助理反击_主题曲_主用版", "助理反击_主题曲_主歌副歌版"),
    "end": ("助理反击_主题曲_片尾版", "助理反击_主题曲_纯器乐版"),
}
THEME_DIRS = ("05_音频",)


def find_theme_song(workdir: str, kind: str = "main", up_levels: int = 3) -> str:
    """按稳定命名找主题曲，返回路径，找不到返回 ''。

    kind: main=主用版（片头/宣传统一用这条）、end=片尾版（片尾/合集/长版）
    母版名（主歌副歌版/纯器乐版）作为 fallback，保证旧工程不掉。
    """
    names = THEME_NAMES.get(kind) or THEME_NAMES["main"]
    bases = []
    seen = set()

    def _add(base):
        if base not in seen and os.path.isdir(base):
            seen.add(base)
            bases.append(base)

    cur = os.path.abspath(workdir) if workdir else ""
    for _ in range(up_levels + 1):
        if not cur:
            break
        for d in THEME_DIRS:
            _add(os.path.join(cur, d))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for root in _extra_asset_roots():
        for d in THEME_DIRS:
            _add(os.path.join(root, d))

    for nm in names:
        for base in bases:
            for ext in _AUDIO_EXT:
                p = os.path.join(base, "%s.%s" % (nm, ext))
                if os.path.isfile(p) and os.path.getsize(p) > 1024:
                    return p
    return ""


def find_local_asset(workdir: str, kind: str = "music", ep: int = 1,
                     track_key: str = "") -> str:
    """在项目目录里找本地音乐/BGM 素材，找不到返回 ''。

    认这些命名（kind=music）：
        music_ep1.mp3 / music_ep01.mp3 / music.mp3 / <track_key>.mp3
    kind=bgm 同理换 bgm_ 前缀。
    """
    if not workdir or not os.path.isdir(workdir):
        return ""
    names = []
    for e in (str(ep), "%02d" % ep):
        names.append("%s_ep%s" % (kind, e))
    names.append(kind)
    if track_key:
        names.append(str(track_key))
    for d in _ASSET_DIRS:
        base = os.path.join(workdir, d) if d else workdir
        for nm in names:
            for ext in _AUDIO_EXT:
                p = os.path.join(base, "%s.%s" % (nm, ext))
                if os.path.isfile(p) and os.path.getsize(p) > 1024:
                    return p
    return ""


def fit_local_asset(src: str, duration_s: float, out_path: str,
                    fade_ms: int = 1200) -> Dict[str, Any]:
    """把本地素材循环/裁切到目标时长，带淡入淡出避免接缝爆音。"""
    if not src or not os.path.isfile(src):
        return {"ok": False, "path": "", "backend": "local_file",
                "error": "本地素材不存在: %s" % src}
    if not FFMPEG:
        return {"ok": False, "path": "", "backend": "local_file",
                "error": "ffmpeg 不可用"}
    dur = max(1.0, float(duration_s or 0))
    fade = min(fade_ms / 1000.0, dur / 4.0)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    # 素材常常就叫 music_ep1.mp3 / bgm_ep1.mp3，和输出路径完全同一条。
    # ffmpeg 会直接拒绝 "same as Input"，所以必须走临时文件再替换。
    tmp = out_path + ".tmp_fit.mp3"
    cmd = [FFMPEG, "-y", "-v", "error", "-stream_loop", "-1", "-i", src,
           "-t", "%.3f" % dur,
           "-af", "afade=t=in:st=0:d=%.2f,afade=t=out:st=%.2f:d=%.2f"
                  % (fade, max(0.0, dur - fade), fade),
           "-c:a", "libmp3lame", "-q:a", "4", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(tmp):
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "path": "", "backend": "local_file",
                "error": "ffmpeg 失败: %s" % (r.stderr or "")[:300]}
    os.replace(tmp, out_path)
    return {"ok": True, "path": out_path, "backend": "local_file",
            "duration_ms": int(dur * 1000), "source": src, "error": ""}


def generate(spec_or_key, backend: str = "auto", out_path: Optional[str] = None,
             matrix=None, duration_s: int = 30, mood_hint: str = "",
             poll_timeout: int = 600, tmp_dir: str = "music_out",
             local_src: str = "") -> Dict[str, Any]:
    """生成音乐。spec_or_key 可以是 build_music_spec 的结果或 track_key 字符串。

    backend=auto 时：有 SUNO 配置走 suno_api，否则退到 spec_only（只给规格）。
    spec_only 是正式能力，不是失败：白皇拿 style_zh 去 sunoyinyue.com 手动生成。
    """
    spec = spec_or_key if isinstance(spec_or_key, dict) else \
        build_music_spec(spec_or_key, matrix=matrix, duration_s=duration_s,
                         mood_hint=mood_hint)

    if backend in ("", "auto"):
        if local_src:
            backend = "local_file"
        elif _provider_available("suno_api"):
            backend = "suno_api"
        else:
            backend = "spec_only"

    if backend == "local_file":
        _dur = float(spec.get("duration_s") or duration_s or 30)
        if not out_path:
            return {"ok": False, "path": "", "backend": "local_file", "spec": spec,
                    "duration_ms": 0, "error": "local_file 模式必须给 out_path"}
        res = fit_local_asset(local_src, _dur, out_path)
        res["spec"] = spec
        res.setdefault("duration_ms", 0)
        return res

    if backend == "spec_only":
        return {"ok": True, "path": "", "backend": "spec_only",
                "spec": spec, "duration_ms": spec.get("duration_s", 0) * 1000,
                "error": "", "note": "未配置音乐 API，已产出规格；style_zh 可直接用于 sunoyinyue.com 手动生成"}

    os.makedirs(tmp_dir, exist_ok=True)
    if out_path is None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(spec.get("track_key", "music")))
        out_path = os.path.join(tmp_dir, "%s_%d.mp3" % (safe, int(time.time() * 1000)))

    if backend == "suno_api":
        return _do_suno(spec, out_path, poll_timeout)

    return {"ok": False, "path": "", "backend": backend, "spec": spec,
            "duration_ms": 0, "error": "未知后端 %s" % backend}


def export_prompt_sheet(track_keys: List[str], matrix=None,
                        out_path: Optional[str] = None,
                        duration_s: int = 30) -> Dict[str, Any]:
    """批量导出音乐生成清单（人工在 sunoyinyue.com / 其他平台批量生成用）。"""
    specs = []
    for k in track_keys:
        try:
            specs.append(build_music_spec(k, matrix=matrix, duration_s=duration_s))
        except Exception as e:  # noqa: BLE001
            specs.append({"track_key": k, "found": False, "error": str(e)})

    result = {"ok": True, "count": len(specs), "specs": specs}
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        result["out_path"] = out_path
    return result


def plan_episode_music(scenario: str, ep: int = 1, matrix=None,
                       audio_mode: str = "auto", duration_s: int = 30,
                       path: Optional[str] = None) -> Dict[str, Any]:
    """按剧种 + 情绪弧线，规划某一集需要的音乐轨规格清单。

    直接消费 audio_advisor 的选轨结果，把 impl=music_gen./bgm_mix. 的
    曲目 key 转成可投喂音乐模型的规格，是"配合剧本生成音乐"的入口。
    """
    from .audio_advisor import advise_tracks
    m = _matrix(matrix, path)
    tracks = advise_tracks(scenario, m, audio_mode=audio_mode, ep=ep)

    items = []
    for t in tracks:
        impl = str(t.get("impl", ""))
        key = t.get("track_key") or ""
        if impl.startswith("music_gen.") or impl.startswith("bgm_mix."):
            try:
                spec = build_music_spec(key, matrix=m, duration_s=duration_s)
            except Exception as e:  # noqa: BLE001
                spec = {"track_key": key, "found": False, "error": str(e)}
            items.append({"role": t.get("id"), "name": t.get("name"),
                          "impl": impl, "priority": t.get("priority"),
                          "spec": spec})
        else:
            items.append({"role": t.get("id"), "name": t.get("name"),
                          "impl": impl, "priority": t.get("priority"),
                          "spec": None, "note": "非音乐轨，由对应模块处理"})

    return {"ok": True, "scenario": scenario, "ep": ep,
            "audio_mode": audio_mode, "count": len(items), "items": items}


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="音乐轨生成（多后端可插拔）")
    p.add_argument("track_key", nargs="?", default="M28_anime_jpop",
                   help="曲目 key（M*/B*）或自定义")
    p.add_argument("--backend", default="auto",
                   choices=["auto", "suno_api", "spec_only"])
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--mood", default="")
    p.add_argument("--out", default=None)
    p.add_argument("--sheet", action="store_true",
                   help="批量导出清单模式（track_key 用逗号分隔多个）")
    args = p.parse_args(argv)

    if args.sheet:
        keys = [k.strip() for k in args.track_key.split(",") if k.strip()]
        r = export_prompt_sheet(keys, out_path=args.out, duration_s=args.duration)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
        return 0

    r = generate(args.track_key, backend=args.backend, out_path=args.out,
                 duration_s=args.duration, mood_hint=args.mood)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())


__all__ = ["build_music_spec", "generate", "export_prompt_sheet",
           "plan_episode_music", "SUNO_BASE", "SUNO_MODEL"]
