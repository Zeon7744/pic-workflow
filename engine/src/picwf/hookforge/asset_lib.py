# -*- coding: utf-8 -*-
"""L0 资产库：manifest.json 是依赖图。

manifest 结构：
{
  "version": 1,
  "updated_at": iso,
  "episodes": {"1": ["shot_ep1_001", ...]},
  "reverse_refs": {"char_沈临": ["shot_ep1_002", ...], "bgm_suspense": [...]},
  "asset_dirs": {...}
}

规则：
- 每个 asset 一个 json（带 version + history[]），文件本体在 asset_dirs 指的路径
- shot 只存引用（characters / bgm 数组），不内嵌外观文本
- 改一个 asset = 版本 +1，reverse_refs 里引用它的 shot 全标脏
"""
import json
import os
import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional


class AssetLibrary:
    """manifest 依赖图 + 脏分镜计算。"""

    def __init__(self, root: str):
        self.root = root
        self.path = os.path.join(root, "manifest.json")
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"manifest.json 不存在: {self.path}")
        with open(self.path, encoding="utf-8") as f:
            self.manifest: Dict[str, Any] = json.load(f)
        self._dirty_cache: Dict[str, List[str]] = {}

    # ---------- 脏分镜 ----------

    def dirty_shots_for_asset(self, asset_id: str) -> List[str]:
        """改 asset_id 后，哪些 shot 需要重出。"""
        return sorted(self.manifest.get("reverse_refs", {}).get(asset_id, []))

    def is_dirty(self, asset_id: str, since_version: int) -> bool:
        """改到 >= since_version 时，下游 shot 是否需要重跑。"""
        p = self._asset_path(asset_id)
        if not p:
            return True
        a = self._load_asset(asset_id)
        return int(a.get("version") or 1) > int(since_version)

    # ---------- 读写 ----------

    def _asset_path(self, asset_id: str) -> Optional[str]:
        """asset_id -> json 路径（在 characters/、voices/ 目录搜）。"""
        for sub in ("characters", "voices", "scenes"):
            p = os.path.join(self.root, sub, f"{asset_id}.json")
            if os.path.isfile(p):
                return p
        return None

    def load(self, asset_id: str) -> Dict[str, Any]:
        p = self._asset_path(asset_id)
        if not p:
            raise FileNotFoundError(f"asset 未找到: {asset_id}")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def load_shot(self, shot_id: str) -> Dict[str, Any]:
        ep = str(shot_id).split("_")[1]  # shot_ep1_001 -> ep1
        p = os.path.join(self.root, "shots", ep, f"{shot_id}.json")
        if not os.path.isfile(p):
            raise FileNotFoundError(f"shot 未找到: {p}")
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def bump_version(self, asset_id: str, action: str) -> Dict[str, Any]:
        """version +1 并追加 history；同时把 reverse_refs 里引用它的 shot 标脏。"""
        a = self.load(asset_id)
        a["version"] = int(a.get("version") or 0) + 1
        a["history"] = a.get("history", []) + [{
            "version": a["version"], "action": action,
            "timestamp": datetime.now().isoformat(),
            "prev_checksum": a.get("checksum", ""),
        }]
        a["checksum"] = hashlib.sha256(
            json.dumps(a, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        p = self._asset_path(asset_id)
        assert p
        with open(p, "w", encoding="utf-8") as f:
            json.dump(a, f, ensure_ascii=False, indent=2)
        # 标脏：把 reverse_refs 里该 asset 的 shot 存到 dirty 标记
        dirty = self.dirty_shots_for_asset(asset_id)
        self._dirty_cache[asset_id] = dirty
        self.manifest.setdefault("dirty", {})[asset_id] = {
            "since_version": a["version"], "dirty_shots": dirty,
            "marked_at": datetime.now().isoformat(),
        }
        self._save_manifest()
        return a

    def clear_dirty(self, asset_id: str):
        """重跑完下游 shot 后清掉脏标记。"""
        self.manifest.get("dirty", {}).pop(asset_id, None)
        self._save_manifest()

    def _save_manifest(self):
        self.manifest["updated_at"] = datetime.now().isoformat()
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)

    def episodes(self) -> List[int]:
        return sorted(self.manifest.get("episodes", {}).keys(), key=lambda x: int(x))
