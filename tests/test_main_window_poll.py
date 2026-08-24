from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from overwatch_drops_miner.gui_parts.app_style import configure_qt_app
from overwatch_drops_miner.gui_parts.gui_state import GuiStateStore
from overwatch_drops_miner.gui_parts.main_window import MinerGUI


class MainWindowPollTests(unittest.TestCase):
    """H5 修复回归测试：崩溃后停止轮询计时器生命周期与启动失败分支。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_qt_app(cls.app)

    def _make_window(self) -> MinerGUI:
        temp_dir = tempfile.mkdtemp(prefix="owtest_gui_poll_")
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        settings = QSettings(
            str(Path(temp_dir) / "gui.ini"), QSettings.IniFormat
        )
        window = MinerGUI(gui_state=GuiStateStore(settings))
        window._stop_poll_timer.stop()
        window._config_sync_timer.stop()
        window._watch_tick_timer.stop()
        window._log_timer.stop()
        return window

    def test_poll_shutdown_all_keeps_polling_until_clean(self) -> None:
        """崩溃场景下首轮 stopped 不停表，全部回收（no_thread）才停表。"""
        window = self._make_window()
        try:
            manager = MagicMock()
            manager.shutdown_states.return_value = {"a": "idle"}
            manager.poll_shutdown.side_effect = ["stopped", "no_thread"]
            window.miner_manager = manager

            window._stop_poll_timer.start()
            self.assertTrue(window._stop_poll_timer.isActive())

            # 第一轮：刚完成一次死线程清理，必须继续轮询确认。
            window._poll_shutdown_all()
            self.assertTrue(
                window._stop_poll_timer.isActive(),
                "首轮返回 stopped 时不应提前停止轮询计时器",
            )

            # 第二轮：确认已全部回收，此时才允许停表。
            window._poll_shutdown_all()
            self.assertFalse(window._stop_poll_timer.isActive())
            self.assertEqual(manager.poll_shutdown.call_count, 2)
        finally:
            window.close()

    def test_poll_shutdown_all_keeps_polling_while_running(self) -> None:
        """仍有活动线程（running）时轮询计时器保持开启。"""
        window = self._make_window()
        try:
            manager = MagicMock()
            manager.shutdown_states.return_value = {"a": "running"}
            manager.poll_shutdown.return_value = "running"
            window.miner_manager = manager

            window._stop_poll_timer.start()
            window._poll_shutdown_all()
            self.assertTrue(window._stop_poll_timer.isActive())
        finally:
            window.close()

    def test_start_account_failure_warns_after_cleanup(self) -> None:
        """启动失败时先尝试回收残留线程，仍失败则弹出警告且不抛异常。"""
        window = self._make_window()
        try:
            window.rooms_edit.setText("123")
            account = SimpleNamespace(
                id="test-account",
                remark="测试账号",
                cookie=lambda: "SESSDATA=xxx; bili_jct=xxx",
            )
            manager = MagicMock()
            manager.is_running.return_value = False
            manager.start.side_effect = [False, False]
            manager.poll_shutdown.return_value = "stopped"
            manager.running_count.return_value = 0
            manager.tracker.return_value = None
            window.miner_manager = manager

            with (
                patch.object(
                    window.account_store, "get", return_value=account
                ),
                patch.object(MinerGUI, "_show_warning") as warn,
                patch.object(MinerGUI, "_install_logging", lambda self: None),
            ):
                window.start_account("test-account")

            # 首次 start 失败 -> 回收一次 -> 二次 start 仍失败 -> 警告。
            self.assertEqual(manager.start.call_count, 2)
            manager.poll_shutdown.assert_called_once()
            warn.assert_called_once_with(
                "启动失败", "该账号后台尚未完全停止，请稍候几秒后重试。"
            )
        finally:
            window.close()

    def test_start_account_recovers_after_cleanup(self) -> None:
        """首次启动失败、回收成功后二次启动成功，走正常启动收尾且无警告。"""
        window = self._make_window()
        try:
            window.rooms_edit.setText("123")
            account = SimpleNamespace(
                id="test-account",
                remark="测试账号",
                cookie=lambda: "SESSDATA=xxx; bili_jct=xxx",
            )
            manager = MagicMock()
            manager.is_running.return_value = False
            manager.start.side_effect = [False, True]
            manager.poll_shutdown.return_value = "stopped"
            manager.running_count.return_value = 1
            manager.tracker.return_value = None
            window.miner_manager = manager

            with (
                patch.object(
                    window.account_store, "get", return_value=account
                ),
                patch.object(MinerGUI, "_show_warning") as warn,
                patch.object(MinerGUI, "_install_logging", lambda self: None),
            ):
                window.start_account("test-account")

            self.assertEqual(manager.start.call_count, 2)
            warn.assert_not_called()
            self.assertTrue(window._stop_poll_timer.isActive())
        finally:
            window.close()


    def test_close_flow_polls_until_no_thread(self) -> None:
        """closeEvent 后渐进轮询，全部账号线程回收（no_thread）才调用退出。"""
        window = self._make_window()
        try:
            manager = MagicMock()
            manager.shutdown_states.return_value = {"a": "idle"}
            manager.poll_shutdown.side_effect = ["stopped", "no_thread"]
            window.miner_manager = manager

            with (
                patch.object(window.browser_actions, "shutdown", return_value=True),
                patch.object(MinerGUI, "_quit_app") as quit_mock,
            ):
                # closeEvent 只触发渐进关窗，不立即退出。
                window.close()
                manager.stop_all.assert_called_once()
                quit_mock.assert_not_called()

                # 第一轮仍在线程收尾（stopped），不应退出。
                window._close_poll_step()
                quit_mock.assert_not_called()

                # 第二轮确认全部回收，此时才允许最终退出。
                window._close_poll_step()
                quit_mock.assert_called_once()
                self.assertEqual(manager.poll_shutdown.call_count, 2)
        finally:
            window.close()

    def test_remove_account_discards_stale_task_result(self) -> None:
        """删除账号后迟到的任务结果回调应被丢弃，不再写回结果表。"""
        window = self._make_window()
        try:
            account = SimpleNamespace(id="gone-account", remark="待删除账号")
            store = MagicMock()
            store.get.return_value = account
            store.list_accounts.return_value = []
            window.account_store = store
            manager = MagicMock()
            manager.is_running.return_value = True
            manager.running_count.return_value = 0
            window.miner_manager = manager

            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                window.remove_account("gone-account")

            self.assertNotIn("gone-account", window._task_controllers)
            self.assertNotIn("gone-account", window._task_progress_results)

            # 模拟凭据已删除：此后按 id 查询账号应不存在。
            store.get.return_value = None

            # 模拟后台线程完成后经 post_ui_task 迟到回写结果。
            window._set_task_progress_text("gone-account", "迟到的任务结果")

            self.assertNotIn(
                "gone-account",
                window._task_progress_results,
                "已删除账号的迟到任务结果不应复活条目",
            )
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
