# -*- coding: utf-8 -*-
"""API Key 配置：支持 .env / 环境变量 / 配置文件三种来源。"""
import os
from pathlib import Path
from typing import Dict, Optional

DEFAULT_KEYS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "api_keys.env"

def _load_dotenv(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if not path.exists():
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip("\"'")
            env[k.strip()] = v
    return env

_CACHE: Optional[Dict[str, str]] = None

def load_api_keys(path: Optional[Path] = None) -> Dict[str, str]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    p = path or DEFAULT_KEYS_PATH
    env = _load_dotenv(p)
    for k in ("WAN_API_KEY", "KLING_API_KEY", "SEEDREAM_API_KEY", "AGNES_IMAGE_API_KEY", "AGNES_VIDEO_API_KEY", "TTS_OPENAI_API_KEY", "TTS_OPENAI_BASE_URL", "TTS_OPENAI_MODEL", "TTS_EDGE", "MINIMAX_API_KEY", "MINIMAX_BASE_URL"):
        env.setdefault(k, os.environ.get(k, ""))
    _CACHE = env
    return env

def get_key(service: str) -> str:
    keys = load_api_keys()
    mapping = {
        "wan": keys.get("WAN_API_KEY", ""),
        "kling": keys.get("KLING_API_KEY", ""),
        "seedream": keys.get("SEEDREAM_API_KEY", ""),
        "agnes_image": keys.get("AGNES_IMAGE_API_KEY", ""),
        "agnes_video": keys.get("AGNES_VIDEO_API_KEY", ""),
        "minimax": keys.get("MINIMAX_API_KEY", ""),
    }
    val = mapping.get(service, "")
    if not val:
        val = _read_key_file(service)
    return val

# 项目级 key 文件兜底：/Coze/Drive/简化画廊/.agnes_key 等
_KEY_FILES = {
    "agnes_video": ".agnes_key",
    "agnes_image": ".agnes_key",
}
_KEY_SEARCH = [
    "/Coze/Drive/简化画廊",                      # 云端项目共享目录
    "~",                                         # 用户 home
    ".",                                         # 当前工作目录
]


def _read_key_file(service: str) -> str:
    """从 .agnes_key 之类的项目级 key 文件读密钥（红剑 22:19 指定路径）。"""
    fname = _KEY_FILES.get(service)
    if not fname:
        return ""
    import pathlib
    for base in _KEY_SEARCH:
        p = pathlib.Path(base).expanduser() / fname
        try:
            if p.is_file():
                txt = p.read_text(encoding="utf-8").strip()
                if txt:
                    return txt
        except OSError:
            continue
    return ""


def has_key(service: str) -> bool:
    return bool(get_key(service))
