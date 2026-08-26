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
from overwatch_drops_miner.gui_parts.main_window import (
    KEY_AUTO_CLAIM,
    KEY_DISABLE_TASK_NOTIFY,
    KEY_RECONNECT_DELAY,
    KEY_ROOMS,
    KEY_TASK_INTERVAL,
    KEY_THREAD_COUNT,
    KEY_VERBOSE,
    MinerGUI,
)


class GuiPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_qt_app(cls.app)

    @staticmethod
    def _state_for(directory: str) -> GuiStateStore:
        settings = QSettings(
            str(Path(directory) / "gui.ini"),
            QSettings.IniFormat,
        )
        return GuiStateStore(settings)

    def test_window_geometry_is_saved_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_for(temp_dir)
            first = MinerGUI(gui_state=state)
            first.resize(1200, 800)
            geometry = first.saveGeometry()
            first.close()

            second = MinerGUI(gui_state=state)
            self.assertTrue(second.restoreGeometry(geometry))
            second.close()

    def test_exit_saves_shared_config_and_restores_on_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_for(temp_dir)
            window = MinerGUI(gui_state=state)
            window.rooms_edit.setText("123, 456")
            window.notify_urls_edit.setText("gotify://example.invalid/token")
            window.threads_spin.setValue(64)
            window.reconnect_spin.setValue(12)
            window.task_interval_spin.setValue(45)
            window.verbose_check.setChecked(True)
            window.disable_task_notify_check.setChecked(True)
            window.auto_claim_rewards_check.setChecked(True)
            window.close()

            restored = MinerGUI(gui_state=state)
            try:
                self.assertEqual(restored.rooms_edit.text(), "123, 456")
                self.assertEqual(
                    restored.notify_urls_edit.text(),
                    "gotify://example.invalid/token",
                )
                self.assertEqual(restored.threads_spin.value(), 64)
                self.assertEqual(restored.reconnect_spin.value(), 12)
                self.assertEqual(restored.task_interval_spin.value(), 45)
                self.assertTrue(restored.verbose_check.isChecked())
                self.assertTrue(restored.disable_task_notify_check.isChecked())
                self.assertTrue(restored.auto_claim_rewards_check.isChecked())
            finally:
                restored.close()

    def test_task_ids_are_never_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_for(temp_dir)
            window = MinerGUI(gui_state=state)
            window.task_ids_edit.setText("task-a,task-b")
            window.close()

            self.assertEqual(
                str(state.value("config/task_ids_text", "") or ""), ""
            )
            restored = MinerGUI(gui_state=state)
            try:
                self.assertEqual(restored.task_ids_edit.text(), "")
            finally:
                restored.close()

    def test_shared_config_keys_are_written_on_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_for(temp_dir)
            window = MinerGUI(gui_state=state)
            window.rooms_edit.setText("777")
            window.close()

            self.assertEqual(str(state.value(KEY_ROOMS, "")), "777")
            self.assertIsNotNone(state.value(KEY_THREAD_COUNT, None))
            self.assertIsNotNone(state.value(KEY_RECONNECT_DELAY, None))
            self.assertIsNotNone(state.value(KEY_TASK_INTERVAL, None))
            self.assertIsNotNone(state.value(KEY_VERBOSE, None))
            self.assertIsNotNone(state.value(KEY_DISABLE_TASK_NOTIFY, None))
            self.assertIsNotNone(state.value(KEY_AUTO_CLAIM, None))

    def test_first_launch_geometry_intersects_primary_screen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            window = MinerGUI(gui_state=self._state_for(temp_dir))
            try:
                screen = self.app.primaryScreen().availableGeometry()
                self.assertTrue(screen.intersects(window.frameGeometry()))
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()



class NotifyUrlParsingRegressionTest(GuiPersistenceTests):
    """T-3/H-1 回归：含 & 的通知 URL 不得被截断或做 task_ids= 提取。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_qt_app(cls.app)

    def test_ampersand_urls_survive_config_build(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = self._state_for(temp_dir)
            window = MinerGUI(gui_state=state)
            try:
                window.rooms_edit.setText("123")
                window.notify_urls_edit.setText(
                    "gotify://example.invalid/token?priority=8&nosound=true"
                )
                config = window._build_shared_config()
                self.assertEqual(
                    config.notify_urls,
                    ["gotify://example.invalid/token?priority=8&nosound=true"],
                )
            finally:
                window.close()

