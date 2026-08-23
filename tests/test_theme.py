from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from overwatch_drops_miner.gui_parts.app_style import configure_qt_app
from overwatch_drops_miner.gui_parts.gui_state import GuiStateStore
from overwatch_drops_miner.gui_parts.theme import (
    DARK,
    LIGHT,
    TOKENS,
    ThemeManager,
    build_stylesheet,
    detect_system_theme,
)


class ThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_qt_app(cls.app)

    @staticmethod
    def _state_for(directory: str) -> GuiStateStore:
        settings = QSettings(
            str(Path(directory) / "gui.ini"), QSettings.IniFormat
        )
        return GuiStateStore(settings)

    def test_tokens_cover_both_themes(self) -> None:
        self.assertIn(DARK, TOKENS)
        self.assertIn(LIGHT, TOKENS)
        for name, tokens in TOKENS.items():
            self.assertEqual(tokens.name, name)
            self.assertTrue(tokens.bg.startswith("#"))
            self.assertTrue(tokens.accent.startswith("#"))
            self.assertTrue(tokens.success.startswith("#"))
            self.assertTrue(tokens.danger.startswith("#"))

    def test_stylesheet_contains_accent_selectors(self) -> None:
        for tokens in TOKENS.values():
            qss = build_stylesheet(tokens)
            self.assertIn('QPushButton[accent="primary"]', qss)
            self.assertIn('QPushButton[accent="success"]', qss)
            self.assertIn('QPushButton[accent="danger"]', qss)
            self.assertIn('QPushButton[accent="purple"]', qss)
            self.assertIn('QPushButton[accent="neutral"]', qss)
            self.assertIn("QToolTip", qss)

    def test_manager_defaults_and_toggle_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_for(temp_dir)
            manager = ThemeManager(self.app, state)
            initial = manager.theme
            self.assertIn(initial, TOKENS)

            manager.toggle()
            self.assertEqual(manager.theme, LIGHT if initial == DARK else DARK)
            state.sync()

            reloaded = ThemeManager(self.app, self._state_for(temp_dir))
            self.assertEqual(reloaded.theme, manager.theme)

    def test_detect_system_theme_returns_valid_theme(self) -> None:
        self.assertIn(detect_system_theme(), TOKENS)


if __name__ == "__main__":
    unittest.main()
