from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QSpinBox

from overwatch_drops_miner.gui_parts.main_layout import (
    MAX_THREAD_COUNT,
    THREADS_TOOLTIP,
    MainWindowCallbacks,
    build_main_window_layout,
)


def _noop(*args, **kwargs) -> None:
    return None


class MainLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_build_main_window_layout_returns_expected_widgets(self) -> None:
        window = QMainWindow()
        calls: list[str] = []
        callbacks = MainWindowCallbacks(
            start=lambda: calls.append("start"),
            stop=lambda: calls.append("stop"),
            load_config=_noop,
            save_config=_noop,
            clear_logs=_noop,
            claim_rewards=_noop,
            refresh_tasks=_noop,
            toggle_log=_noop,
            auto_fetch_room_id=_noop,
            auto_fetch_task_ids_mode1=_noop,
            auto_fetch_task_ids_mode2=_noop,
            toggle_theme=_noop,
        )
        widgets = build_main_window_layout(window, callbacks)
        try:
            self.assertEqual(widgets.rooms_edit.text(), "23612045")
            self.assertEqual(widgets.threads_spin.value(), 1)
            self.assertEqual(widgets.threads_spin.maximum(), MAX_THREAD_COUNT)
            self.assertEqual(widgets.threads_spin.toolTip(), THREADS_TOOLTIP)
            self.assertEqual(widgets.reconnect_edit.text(), "8")
            self.assertEqual(widgets.task_interval_edit.text(), "30")
            self.assertEqual(
                widgets.account_status_label.text(), "未选择账号"
            )
            self.assertEqual(widgets.account_status_label.textFormat(), Qt.PlainText)
            self.assertFalse(widgets.log_text.isVisible())
            self.assertFalse(widgets.progress_bar.isVisible())
            self.assertIsInstance(widgets.threads_spin, QSpinBox)
            self.assertEqual(widgets.task_progress_bar.minimum(), 0)
            self.assertEqual(widgets.task_progress_bar.maximum(), 100)
            self.assertEqual(widgets.theme_button.text(), "切换主题")
            self.assertIsNotNone(widgets.account_panel)
        finally:
            window.deleteLater()

    def test_thread_spinbox_enforces_upper_bound(self) -> None:
        window = QMainWindow()
        callbacks = MainWindowCallbacks(
            start=_noop,
            stop=_noop,
            load_config=_noop,
            save_config=_noop,
            clear_logs=_noop,
            claim_rewards=_noop,
            refresh_tasks=_noop,
            toggle_log=_noop,
            auto_fetch_room_id=_noop,
            auto_fetch_task_ids_mode1=_noop,
            auto_fetch_task_ids_mode2=_noop,
            toggle_theme=_noop,
        )
        widgets = build_main_window_layout(window, callbacks)
        try:
            widgets.threads_spin.setValue(999)
            self.assertEqual(widgets.threads_spin.value(), MAX_THREAD_COUNT)
            widgets.threads_spin.setValue(0)
            self.assertEqual(widgets.threads_spin.value(), 1)
        finally:
            window.deleteLater()

    def test_start_button_wired_to_callback(self) -> None:
        window = QMainWindow()
        calls: list[str] = []
        callbacks = MainWindowCallbacks(
            start=lambda: calls.append("start"),
            stop=lambda: calls.append("stop"),
            load_config=_noop,
            save_config=_noop,
            clear_logs=_noop,
            claim_rewards=_noop,
            refresh_tasks=_noop,
            toggle_log=_noop,
            auto_fetch_room_id=_noop,
            auto_fetch_task_ids_mode1=_noop,
            auto_fetch_task_ids_mode2=_noop,
            toggle_theme=_noop,
        )
        widgets = build_main_window_layout(window, callbacks)
        try:
            widgets.start_btn.click()
            widgets.stop_btn.click()
            self.assertEqual(calls, ["start", "stop"])
        finally:
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
