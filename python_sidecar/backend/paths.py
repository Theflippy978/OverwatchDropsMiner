from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR_ENV_VAR = "OW_CONFIG_DIR"
APP_DATA_DIR_NAME = "OverwatchDropsMiner"
ACCOUNTS_FILE_NAME = "accounts.json"
UPDATE_STATE_FILE_NAME = "update_check.json"


def is_isolated() -> bool:
    """True when OW_CONFIG_DIR redirects all persistence for dev/test."""
    return bool(os.environ.get(CONFIG_DIR_ENV_VAR, "").strip())


def get_config_dir() -> Path:
    configured = os.environ.get(CONFIG_DIR_ENV_VAR, "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / APP_DATA_DIR_NAME
    return Path.home() / APP_DATA_DIR_NAME


def get_accounts_path() -> Path:
    return get_config_dir() / ACCOUNTS_FILE_NAME


def get_update_state_path() -> Path:
    """自动更新检查的节流状态（上次检查时间）。

    **刻意不放进 config.json**：那是用户可见、可导入导出的配置，
    而「上次检查于何时」是纯粹的本机运行状态 —— 混进去会让导出文件
    带上一堆与用户无关的字段，也会让「导入配置」意外重置检查节奏。
    """
    return get_config_dir() / UPDATE_STATE_FILE_NAME


# 本模块曾有 create_qsettings / QSETTINGS_FILE_NAME，是 Qt GUI 时代的遗留。
# 它无任何调用者，但函数体内的 `from PySide6.QtCore import QSettings` 会被
# PyInstaller 静态收集，导致整个 Qt（116 项，含 Qt6Core.dll）被打进 sidecar ——
# 而 sidecar 运行时不需要 Qt。删除后打包体积从 60.7MB 降到 44.7MB。
#
# 教训：PyInstaller 会静态收集函数体内的 import，所以「留一个永不调用的函数」
# 足以把整棵依赖树拖进产物。tests/check_dead_modules.py 是模块级可达性分析，
# 本模块因被 accounts.py 引用而判定为「活」，它内部的死函数它发现不了 ——
# 检测器通过不等于没有死代码。
