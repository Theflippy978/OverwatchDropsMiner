from __future__ import annotations

import os
from pathlib import Path

CONFIG_DIR_ENV_VAR = "OW_CONFIG_DIR"
APP_DATA_DIR_NAME = "OverwatchDropsMiner"
QSETTINGS_FILE_NAME = "gui.ini"
ACCOUNTS_FILE_NAME = "accounts.json"


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


def create_qsettings(
    organization: str, application: str
) -> QSettings:
    """Registry-backed settings by default; ini file under OW_CONFIG_DIR when isolated.

    PySide6 只在这里导入：sidecar / Tauri 运行时不需要 Qt，只有旧 Qt GUI
    与 Qt 测试会走到这个函数。
    """
    try:
        from PySide6.QtCore import QSettings
    except ImportError as exc:  # pragma: no cover - 仅在缺少 Qt 的环境触发
        raise RuntimeError(
            "读取/写入 GUI 配置需要 PySide6，请先安装：pip install \"PySide6>=6.5,<7\""
        ) from exc

    if is_isolated():
        config_dir = get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        settings = QSettings(
            str(config_dir / QSETTINGS_FILE_NAME), QSettings.IniFormat
        )
        settings.setFallbacksEnabled(False)
        return settings
    settings = QSettings(organization, application)
    # 注册表分支同样禁用 ini 文件回退，避免配置读写位置不确定
    settings.setFallbacksEnabled(False)
    return settings
