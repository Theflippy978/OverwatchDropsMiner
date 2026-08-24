from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import overwatch_drops_miner.gui as gui_facade
import overwatch_drops_miner.gui_parts.main_window as main_window
from overwatch_drops_miner.gui_parts.account_panel import (
    AccountItemView,
    AccountPanel,
)


class TestGuiFacade(unittest.TestCase):
    def test_reexports_main_window_objects(self) -> None:
        self.assertIs(gui_facade.MinerGUI, main_window.MinerGUI)
        self.assertIs(gui_facade.run_gui, main_window.run_gui)
        self.assertEqual(gui_facade.APP_VERSION, main_window.APP_VERSION)
        self.assertEqual(gui_facade.UPDATE_CHANNEL, main_window.UPDATE_CHANNEL)
        self.assertEqual(gui_facade.LATEST_RELEASE_API, main_window.LATEST_RELEASE_API)
        self.assertEqual(gui_facade.RELEASES_URL, main_window.RELEASES_URL)
        self.assertIs(gui_facade._normalize_version, main_window._normalize_version)

    def test_facade_all_exports_expected_names(self) -> None:
        self.assertEqual(
            gui_facade.__all__,
            [
                "APP_VERSION",
                "LATEST_RELEASE_API",
                "RELEASES_URL",
                "UPDATE_CHANNEL",
                "MinerGUI",
                "_normalize_version",
                "run_gui",
            ],
        )


class TestSetRunningForeground(unittest.TestCase):
    """M1 回归：账号列表停止运行后应清除绿色前景残留。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_set_running_false_clears_foreground(self) -> None:
        panel = AccountPanel()
        self.addCleanup(panel.deleteLater)
        panel.set_accounts([AccountItemView(account_id="acc-1", remark="账号一")])
        item = panel.list_widget.item(0)

        panel.set_running("acc-1", True)
        self.assertIsNotNone(item.data(Qt.ForegroundRole))

        panel.set_running("acc-1", False)
        self.assertIsNone(
            item.data(Qt.ForegroundRole),
            "停止运行后应清除自定义前景色，恢复默认配色",
        )
        self.assertEqual(item.toolTip(), "未运行")


if __name__ == "__main__":
    unittest.main()
