"""HookForge L0 资产库 + L1 统一 runner。

L0：manifest.json 是依赖图，改一个 asset 能算出哪些 shot 脏了。
L1：unified_runner 是四入口（CLI/脚本/画布/API）的唯一真管线。
"""
from .asset_lib import AssetLibrary
from .runner import run, DryRunResult, RunnerConfig
__all__ = ["AssetLibrary", "run", "DryRunResult", "RunnerConfig"]
