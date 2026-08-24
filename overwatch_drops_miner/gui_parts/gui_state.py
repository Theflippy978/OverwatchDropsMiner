from __future__ import annotations

from PySide6.QtCore import QSettings

from overwatch_drops_miner.paths import create_qsettings


SETTINGS_ORGANIZATION = "OverwatchDropsMiner"
SETTINGS_APPLICATION = "OverwatchDropsMiner"


class GuiStateStore:
    """Persist local GUI state without copying configuration contents."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = (
            settings
            if settings is not None
            else create_qsettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        )

    def sync(self) -> None:
        self._settings.sync()

    def value(self, key: str, default):
        return self._settings.value(key, default)

    def setValue(self, key: str, value) -> None:
        self._settings.setValue(key, value)
