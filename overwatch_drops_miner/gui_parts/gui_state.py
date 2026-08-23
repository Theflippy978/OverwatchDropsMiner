from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings


SETTINGS_ORGANIZATION = "OverwatchDropsMiner"
SETTINGS_APPLICATION = "OverwatchDropsMiner"

WINDOW_GEOMETRY_KEY = "main_window/geometry"
LAST_CONFIG_PATH_KEY = "config/last_path"


class GuiStateStore:
    """Persist local GUI state without copying configuration contents."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = (
            settings
            if settings is not None
            else QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        )

    def window_geometry(self) -> QByteArray:
        value = self._settings.value(WINDOW_GEOMETRY_KEY, QByteArray())
        if isinstance(value, QByteArray):
            return QByteArray(value)
        if isinstance(value, (bytes, bytearray)):
            return QByteArray(value)
        return QByteArray()

    def set_window_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue(WINDOW_GEOMETRY_KEY, geometry)

    def last_config_path(self) -> Path | None:
        value = self._settings.value(LAST_CONFIG_PATH_KEY, "")
        path_text = str(value or "").strip()
        if not path_text:
            return None
        return Path(path_text)

    def set_last_config_path(self, path: str | Path) -> None:
        normalized = Path(path).expanduser().resolve(strict=False)
        self._settings.setValue(LAST_CONFIG_PATH_KEY, str(normalized))

    def clear_last_config_path(self) -> None:
        self._settings.remove(LAST_CONFIG_PATH_KEY)

    def sync(self) -> None:
        self._settings.sync()
