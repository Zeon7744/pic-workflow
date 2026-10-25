# -*- coding: utf-8 -*-
"""platform_spec：平台规格档案 + 成片裁剪/合规校验（交付端最后一公里）。

为什么需要它
------------
红果短剧、抖音、快手、视频号对同一条片子给出的约束并不一样：
时长上限、宽高比、码率、字幕安全区、首帧封面规格都不同。
现有仓库里 ``package_publish`` 节点只负责"打包"，没有任何模块回答
"这条片子投到红果行不行、要不要裁成竖屏、字幕会不会被 UI 挡住"。

本模块提供：
  1. ``PLATFORM_SPECS``   —— 8 个平台的规格档案（数据来自平台公开创作规范）
  2. ``get_spec``         —— 取平台规格（支持别名）
  3. ``check_compliance`` —— 逐项核对成片参数，返回可执行的修正建议
  4. ``plan_export``      —— 生成目标平台的导出参数（ffmpeg 风格 dict）
  5. ``plan_batch_export``—— 多平台一次导出（各平台一份参数）

规格档案字段::

    {
      "platform": "redfruit",
      "label": "红果短剧",
      "max_duration_s": 180,
      "min_duration_s": 30,
      "aspect_ratio": "9:16",
      "resolution": (1080, 1920),
      "fps": 30,
      "video_bitrate_kbps": (4000, 8000),
      "max_file_mb": 200,
      "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
      "subtitle_safe_area": {"top": 0.12, "bottom": 0.18, "left": 0.08, "right": 0.08},
      "cover": {"width": 1080, "height": 1920, "format": "jpg"},
      "title_max_len": 30,
      "require_watermark": False,
      "notes": "...",
    }
"""
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 平台规格档案
# ---------------------------------------------------------------------------
PLATFORM_SPECS: Dict[str, Dict[str, Any]] = {
    "redfruit": {
        "platform": "redfruit",
        "label": "红果短剧",
        "min_duration_s": 30,
        "max_duration_s": 180,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1920),
        "fps": 30,
        "video_bitrate_kbps": (4000, 8000),
        "max_file_mb": 200,
        "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.10, "bottom": 0.20, "left": 0.06, "right": 0.06},
        "cover": {"width": 1080, "height": 1920, "format": "jpg"},
        "title_max_len": 30,
        "require_watermark": False,
        "notes": "免费短剧分发，主推 1-3 分钟竖屏集；首帧即封面，需保证首帧有信息量",
    },
    "douyin": {
        "platform": "douyin",
        "label": "抖音",
        "min_duration_s": 15,
        "max_duration_s": 600,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1920),
        "fps": 30,
        "video_bitrate_kbps": (2500, 6000),
        "max_file_mb": 500,
        "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.15, "bottom": 0.22, "left": 0.08, "right": 0.08},
        "cover": {"width": 1080, "height": 1920, "format": "jpg"},
        "title_max_len": 55,
        "require_watermark": False,
        "notes": "前 3 秒决定完播；底部约 22% 被交互栏遮挡，字幕必须上移",
    },
    "kuaishou": {
        "platform": "kuaishou",
        "label": "快手",
        "min_duration_s": 15,
        "max_duration_s": 600,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1920),
        "fps": 30,
        "video_bitrate_kbps": (2500, 6000),
        "max_file_mb": 500,
        "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.15, "bottom": 0.20, "left": 0.08, "right": 0.08},
        "cover": {"width": 1080, "height": 1920, "format": "jpg"},
        "title_max_len": 55,
        "require_watermark": False,
        "notes": "老铁向内容偏生活化，标题口语化更好",
    },
    "shipinhao": {
        "platform": "shipinhao",
        "label": "微信视频号",
        "min_duration_s": 15,
        "max_duration_s": 900,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1920),
        "fps": 30,
        "video_bitrate_kbps": (2000, 5000),
        "max_file_mb": 500,
        "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.14, "bottom": 0.20, "left": 0.08, "right": 0.08},
        "cover": {"width": 1080, "height": 1920, "format": "jpg"},
        "title_max_len": 22,
        "require_watermark": False,
        "notes": "社交推荐为主，标题短；分享卡片用 1:1 封面",
    },
    "kuaishou_short": {
        "platform": "kuaishou_short",
        "label": "快手短剧",
        "min_duration_s": 30,
        "max_duration_s": 180,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1920),
        "fps": 30,
        "video_bitrate_kbps": (4000, 8000),
        "max_file_mb": 200,
        "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.10, "bottom": 0.20, "left": 0.06, "right": 0.06},
        "cover": {"width": 1080, "height": 1920, "format": "jpg"},
        "title_max_len": 30,
        "require_watermark": False,
        "notes": "短剧分账通道，与红果同期投喂",
    },
    "bilibili": {
        "platform": "bilibili",
        "label": "哔哩哔哩",
        "min_duration_s": 30,
        "max_duration_s": 1800,
        "aspect_ratio": "16:9",
        "resolution": (1920, 1080),
        "fps": 30,
        "video_bitrate_kbps": (4000, 12000),
        "max_file_mb": 2048,
        "audio": {"codec": "aac", "sample_rate": 48000, "bitrate_kbps": 192},
        "subtitle_safe_area": {"top": 0.08, "bottom": 0.12, "left": 0.05, "right": 0.05},
        "cover": {"width": 1920, "height": 1080, "format": "jpg"},
        "title_max_len": 80,
        "require_watermark": False,
        "notes": "横屏友好，长视频可承载完整剧集；分区与标签影响推荐",
    },
    "xhs": {
        "platform": "xhs",
        "label": "小红书",
        "min_duration_s": 15,
        "max_duration_s": 300,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1440),
        "fps": 30,
        "video_bitrate_kbps": (2000, 5000),
        "max_file_mb": 500,
        "audio": {"codec": "aac", "sample_rate": 44100, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.12, "bottom": 0.20, "left": 0.08, "right": 0.08},
        "cover": {"width": 1080, "height": 1440, "format": "jpg"},
        "title_max_len": 20,
        "require_watermark": False,
        "notes": "3:4 竖版更贴合信息流；封面带标题字更抓人",
    },
    "youtube_shorts": {
        "platform": "youtube_shorts",
        "label": "YouTube Shorts",
        "min_duration_s": 15,
        "max_duration_s": 180,
        "aspect_ratio": "9:16",
        "resolution": (1080, 1920),
        "fps": 30,
        "video_bitrate_kbps": (4000, 10000),
        "max_file_mb": 500,
        "audio": {"codec": "aac", "sample_rate": 48000, "bitrate_kbps": 128},
        "subtitle_safe_area": {"top": 0.12, "bottom": 0.22, "left": 0.10, "right": 0.10},
        "cover": {"width": 1080, "height": 1920, "format": "jpg"},
        "title_max_len": 100,
        "require_watermark": False,
        "notes": "可挂标题文本，右侧 10% 会被 UI 覆盖，字幕要左偏",
    },
}

# 平台别名（用户口语 → 规格 key）
ALIASES = {
    "红果": "redfruit", "红果短剧": "redfruit", "hongguo": "redfruit", "hf": "redfruit",
    "抖音": "douyin", "dy": "douyin", "tiktok": "douyin",
    "快手": "kuaishou", "ks": "kuaishou",
    "视频号": "shipinhao", "微信视频号": "shipinhao", "wechat": "shipinhao",
    "快手短剧": "kuaishou_short",
    "B站": "bilibili", "哔哩哔哩": "bilibili", "b站": "bilibili", "bili": "bilibili",
    "小红书": "xhs", "xiaohongshu": "xhs", "rednote": "xhs",
    "shorts": "youtube_shorts", "yt": "youtube_shorts", "youtube": "youtube_shorts",
}


def _ratio_to_float(r: str) -> float:
    """'9:16' -> 0.5625"""
    try:
        a, b = str(r).split(":")
        return float(a) / float(b)
    except Exception:
        return 0.0


def get_spec(platform: str) -> Dict[str, Any]:
    """取平台规格（支持中文名/别名；未知平台返回空 dict）。"""
    if not platform:
        return {}
    key = str(platform).strip()
    if key in PLATFORM_SPECS:
        return dict(PLATFORM_SPECS[key])
    low = key.lower()
    if low in PLATFORM_SPECS:
        return dict(PLATFORM_SPECS[low])
    if key in ALIASES:
        return dict(PLATFORM_SPECS[ALIASES[key]])
    if low in ALIASES:
        return dict(PLATFORM_SPECS[ALIASES[low]])
    for alias, target in ALIASES.items():
        if alias.lower() == low:
            return dict(PLATFORM_SPECS[target])
    return {}


def list_platforms() -> List[str]:
    """所有平台 key 列表（升序）。"""
    return sorted(PLATFORM_SPECS.keys())


# ---------------------------------------------------------------------------
# 成片合规校验
# ---------------------------------------------------------------------------
def check_compliance(media: Dict[str, Any], platform: str) -> Dict[str, Any]:
    """核对成片参数是否符合平台规格。

    :param media: 成片信息字典，可用键：
        ``duration_s`` / ``width`` / ``height`` / ``fps`` / ``video_bitrate_kbps``
        / ``file_mb`` / ``title_len`` / ``audio_codec`` / ``has_watermark``
    :param platform: 平台名或别名
    :return: ``{"platform","passed","violations","suggestions","spec"}``
        violations 每项含 ``field``/``expected``/``actual``/``level``/``fix``
    """
    spec = get_spec(platform)
    if not spec:
        return {
            "platform": platform,
            "passed": False,
            "violations": [{"field": "platform", "expected": "已知平台",
                            "actual": platform, "level": "block",
                            "fix": "支持平台：" + ", ".join(list_platforms())}],
            "suggestions": [],
            "spec": {},
        }

    v: List[Dict[str, Any]] = []
    media = media or {}

    # 时长
    dur = media.get("duration_s")
    if dur is not None:
        dur = float(dur)
        if dur < spec["min_duration_s"]:
            v.append({"field": "duration_s", "expected": ">=%d" % spec["min_duration_s"],
                      "actual": dur, "level": "block",
                      "fix": "补足内容至 %ds 下限" % spec["min_duration_s"]})
        elif dur > spec["max_duration_s"]:
            v.append({"field": "duration_s", "expected": "<=%d" % spec["max_duration_s"],
                      "actual": dur, "level": "block",
                      "fix": "拆集或压缩至 %ds 以内" % spec["max_duration_s"]})

    # 宽高比
    w = media.get("width")
    h = media.get("height")
    if w and h:
        actual_ratio = float(w) / float(h)
        expect_ratio = _ratio_to_float(spec["aspect_ratio"])
        if expect_ratio and abs(actual_ratio - expect_ratio) > 0.01:
            v.append({"field": "aspect_ratio", "expected": spec["aspect_ratio"],
                      "actual": "%.4f (%dx%d)" % (actual_ratio, w, h), "level": "block",
                      "fix": "重新构图/裁切为 %s" % spec["aspect_ratio"]})
        elif (w, h) != tuple(spec["resolution"]):
            v.append({"field": "resolution", "expected": "%dx%d" % spec["resolution"],
                      "actual": "%dx%d" % (w, h), "level": "warn",
                      "fix": "建议按 %dx%d 输出" % spec["resolution"]})

    # 帧率
    fps = media.get("fps")
    if fps is not None and abs(float(fps) - float(spec["fps"])) > 0.01:
        v.append({"field": "fps", "expected": spec["fps"], "actual": fps,
                  "level": "warn", "fix": "转为 %d fps" % spec["fps"]})

    # 码率
    br = media.get("video_bitrate_kbps")
    if br is not None:
        lo, hi = spec["video_bitrate_kbps"]
        if float(br) < lo:
            v.append({"field": "video_bitrate_kbps", "expected": ">=%d" % lo,
                      "actual": br, "level": "warn",
                      "fix": "提高码率到 %d kbps 以上" % lo})
        elif float(br) > hi:
            v.append({"field": "video_bitrate_kbps", "expected": "<=%d" % hi,
                      "actual": br, "level": "warn",
                      "fix": "降至 %d kbps 以内" % hi})

    # 文件大小
    mb = media.get("file_mb")
    if mb is not None and float(mb) > spec["max_file_mb"]:
        v.append({"field": "file_mb", "expected": "<=%d" % spec["max_file_mb"],
                  "actual": mb, "level": "block",
                  "fix": "压缩至 %d MB 以内" % spec["max_file_mb"]})

    # 标题长度
    tl = media.get("title_len")
    if tl is not None and int(tl) > spec["title_max_len"]:
        v.append({"field": "title_len", "expected": "<=%d" % spec["title_max_len"],
                  "actual": tl, "level": "warn",
                  "fix": "标题精简到 %d 字以内" % spec["title_max_len"]})

    # 音频编码
    ac = media.get("audio_codec")
    if ac and ac.lower() != str(spec["audio"]["codec"]).lower():
        v.append({"field": "audio_codec", "expected": spec["audio"]["codec"],
                  "actual": ac, "level": "warn",
                  "fix": "转码为 %s" % spec["audio"]["codec"]})

    # 水印
    if spec.get("require_watermark") and not media.get("has_watermark"):
        v.append({"field": "has_watermark", "expected": True,
                  "actual": False, "level": "block", "fix": "添加平台水印"})

    blocks = [x for x in v if x["level"] == "block"]
    return {
        "platform": spec["platform"],
        "label": spec["label"],
        "passed": not blocks,
        "violations": v,
        "n_block": len(blocks),
        "n_warn": len(v) - len(blocks),
        "suggestions": [x["fix"] for x in v],
        "spec": spec,
    }


# ---------------------------------------------------------------------------
# 导出参数规划
# ---------------------------------------------------------------------------
def plan_export(media: Dict[str, Any], platform: str) -> Dict[str, Any]:
    """生成目标平台的导出参数（ffmpeg 风格 dict）。

    :param media: 同 ``check_compliance`` 的 media 字典
    :param platform: 平台名或别名
    :return: ``{"platform","ffmpeg","subtitle_safe_area","notes"}``
    """
    spec = get_spec(platform)
    if not spec:
        return {"platform": platform, "ffmpeg": {}, "subtitle_safe_area": {},
                "notes": "未知平台：" + str(platform), "error": "unknown_platform"}

    lo, hi = spec["video_bitrate_kbps"]
    w, h = spec["resolution"]
    fps = spec["fps"]
    ffmpeg = {
        "vf": "scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%d" % (w, h, w, h, fps),
        "c:v": "libx264",
        "preset": "medium",
        "b:v": "%dk" % lo,
        "maxrate": "%dk" % hi,
        "bufsize": "%dk" % (hi * 2),
        "pix_fmt": "yuv420p",
        "c:a": spec["audio"]["codec"],
        "ar": str(spec["audio"]["sample_rate"]),
        "b:a": "%dk" % spec["audio"]["bitrate_kbps"],
        "movflags": "+faststart",
    }
    return {
        "platform": spec["platform"],
        "label": spec["label"],
        "ffmpeg": ffmpeg,
        "resolution": [w, h],
        "aspect_ratio": spec["aspect_ratio"],
        "fps": fps,
        "subtitle_safe_area": spec["subtitle_safe_area"],
        "cover": spec["cover"],
        "notes": spec.get("notes", ""),
    }


def plan_batch_export(media: Dict[str, Any], platforms: List[str]) -> Dict[str, Any]:
    """多平台一次导出。

    返回 ``{"plans": {platform: plan}, "compliance": {platform: result},
    "blocked": [platform...]}``；blocked 表示有 block 级违规、不建议投。
    """
    plans: Dict[str, Any] = {}
    comp: Dict[str, Any] = {}
    blocked: List[str] = []
    for p in platforms or []:
        spec = get_spec(p)
        key = spec.get("platform") if spec else str(p)
        plans[key] = plan_export(media or {}, p)
        res = check_compliance(media or {}, p)
        comp[key] = res
        if not res.get("passed"):
            blocked.append(key)
    return {
        "plans": plans,
        "compliance": comp,
        "blocked": blocked,
        "publishable": [k for k in plans if k not in blocked],
    }
