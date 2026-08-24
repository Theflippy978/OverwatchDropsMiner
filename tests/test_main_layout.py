from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QStyle,
)

from overwatch_drops_miner.gui_parts.main_layout import (
    MAX_THREAD_COUNT,
    THREADS_TOOLTIP,
    MainWindowCallbacks,
    apply_start_stop_button_state,
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

    def test_scroll_area_reserves_vertical_scrollbar_width(self) -> None:
        """最小宽度须预留垂直滚动条宽度且禁用水平滚动条。

        展开日志出现垂直滚动条时占用预留宽度，viewport 宽度不变、
        内容不被挤压，因此水平方向永远不需要滚动（杜绝左右翻页）。
        """
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
            content_min = widgets.scroll_content.minimumSizeHint()
            scrollbar_extent = widgets.content_scroll.style().pixelMetric(
                QStyle.PM_ScrollBarExtent, None, widgets.content_scroll
            )
            self.assertEqual(
                widgets.content_scroll.minimumWidth(),
                content_min.width() + scrollbar_extent,
            )
            self.assertEqual(
                widgets.content_scroll.horizontalScrollBarPolicy(),
                Qt.ScrollBarAlwaysOff,
            )
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

    def test_widgets_expose_distinct_start_stop_buttons(self) -> None:
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
            # 启停按钮引用必须暴露且为两个不同实例，供主窗口状态机联动。
            self.assertIsNot(widgets.start_btn, widgets.stop_btn)
            self.assertEqual(widgets.start_btn.text(), "启动")
            self.assertEqual(widgets.stop_btn.text(), "停止")
        finally:
            window.deleteLater()

    def test_apply_start_stop_button_state_matrix(self) -> None:
        window = QMainWindow()
        try:
            start_btn = QPushButton(window)
            stop_btn = QPushButton(window)
            # (有选中账号, 运行中) -> (启动可用, 停止可用)
            cases: list[tuple[bool, bool, bool, bool]] = [
                (False, False, False, False),  # 未选账号：全禁用
                (True, False, True, False),  # 选中未运行：启动可用
                (True, True, False, True),  # 选中运行中：仅停止可用
            ]
            for has_selection, running, start_enabled, stop_enabled in cases:
                apply_start_stop_button_state(
                    start_btn,
                    stop_btn,
                    has_selection=has_selection,
                    running=running,
                )
                self.assertEqual(
                    start_btn.isEnabled(),
                    start_enabled,
                    f"has_selection={has_selection}, running={running}",
                )
                self.assertEqual(
                    stop_btn.isEnabled(),
                    stop_enabled,
                    f"has_selection={has_selection}, running={running}",
                )
        finally:
            window.deleteLater()


if __name__ == "__main__":
    unittest.main()
