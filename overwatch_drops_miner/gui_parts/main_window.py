from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMessageBox,
)

from overwatch_drops_miner.account_log_context import get_current_account
from overwatch_drops_miner.accounts import Account, AccountStore
from overwatch_drops_miner.config import MinerConfig
from overwatch_drops_miner.gui_parts.account_panel import AccountItemView
from overwatch_drops_miner.gui_parts.app_style import configure_qt_app
from overwatch_drops_miner.gui_parts.browser_actions import BrowserActions
from overwatch_drops_miner.gui_parts.config_io import (
    GuiConfigValues,
    build_config_payload,
    load_config_data,
    save_config_data,
    values_from_config_data,
)
from overwatch_drops_miner.gui_parts.gui_state import GuiStateStore
from overwatch_drops_miner.gui_parts.log_handler import QueueLogHandler
from overwatch_drops_miner.gui_parts.main_layout import (
    MainWindowCallbacks,
    build_main_window_layout,
)
from overwatch_drops_miner.gui_parts.qr_login_dialog import QrLoginDialog
from overwatch_drops_miner.gui_parts.task_controller import TaskController
from overwatch_drops_miner.gui_parts.text_input_dialog import TextInputDialog
from overwatch_drops_miner.gui_parts.theme import ThemeManager
from overwatch_drops_miner.gui_parts.update_checker import (
    check_latest_release,
    normalize_version,
    should_check_update,
)
from overwatch_drops_miner.gui_parts.update_dialog import show_update_available_dialog
from overwatch_drops_miner.logging_utils import setup_logging
from overwatch_drops_miner.miner_manager import AccountMinerManager
from overwatch_drops_miner.utils import parse_room_ids, parse_task_ids

try:
    from overwatch_drops_miner._version import (
        APP_VERSION,
        LATEST_RELEASE_API,
        RELEASES_URL,
        UPDATE_CHANNEL,
    )
except Exception:
    APP_VERSION = "0.0.0+dev"
    UPDATE_CHANNEL = "dev"
    LATEST_RELEASE_API = (
        "https://api.github.com/repos/mi0e/OverwatchDropsMiner/releases/latest"
    )
    RELEASES_URL = "https://github.com/mi0e/OverwatchDropsMiner/releases/latest"


LOGGER = logging.getLogger(__name__)

LOG_BUFFER_SIZE = 5000

# 退出保存的共享配置键（任务 ID 明确不保存）。
KEY_ROOMS = "config/rooms_text"
KEY_NOTIFY_URLS = "config/notify_urls_text"
KEY_THREAD_COUNT = "config/thread_count"
KEY_RECONNECT_DELAY = "config/reconnect_delay"
KEY_TASK_INTERVAL = "config/task_interval"
KEY_VERBOSE = "config/verbose"
KEY_DISABLE_TASK_NOTIFY = "config/disable_task_notify"
KEY_AUTO_CLAIM = "config/auto_claim"


def _normalize_version(value: str) -> str:
    return normalize_version(value)


def _app_icon() -> QIcon:
    for base in (
        Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", "") else None,
        Path.cwd(),
        Path(__file__).resolve().parents[2],
    ):
        if base is None:
            continue
        candidate = base / "img" / "app.ico"
        if candidate.is_file():
            return QIcon(str(candidate))
    return QIcon()


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class MinerGUI(QMainWindow):
    # 跨线程 UI 调度：任意后台线程 emit，Qt 队列到 GUI 线程执行。
    ui_call = Signal(object, tuple, dict)

    def __init__(
        self,
        gui_state: GuiStateStore | None = None,
        theme_manager: ThemeManager | None = None,
    ) -> None:
        super().__init__()
        self._gui_state = gui_state if gui_state is not None else GuiStateStore()
        self.theme_manager = theme_manager
        self.setWindowTitle("守望先锋直播掉宝助手")
        self.setWindowIcon(_app_icon())
        self.resize(1240, 780)
        self.setMinimumSize(1160, 680)
        self._size_expanded = (1240, 940)
        self._size_collapsed = (1240, 780)

        self.log_queue: "queue.Queue[tuple[str | None, str]]" = queue.Queue()
        self._ui_alive = True

        self.account_store = AccountStore()
        self.miner_manager = AccountMinerManager(self._build_config_with_cookie)
        self.miner_manager.add_state_listener(self._on_account_state_thread)

        self._current_account_id: str | None = None
        self._account_logs: dict[str, deque[str]] = {}
        self._system_logs: deque[str] = deque(maxlen=LOG_BUFFER_SIZE)
        self._task_controllers: dict[str, TaskController] = {}
        self._task_progress_results: dict[str, str] = {}
        self._progress_values: dict[str, tuple[float, float]] = {}
        self._task_refresh_pending: set[str] = set()
        self._qr_login_dialog: QrLoginDialog | None = None
        self._adding_accounts = 0
        # 渐进式关窗：等待后台线程退出的截止时刻（time.monotonic 秒）。
        self._shutdown_deadline = 0.0

        self.ui_call.connect(self._on_ui_call, Qt.QueuedConnection)

        self._build_layout()
        self._connect_account_panel()
        self.browser_actions = BrowserActions(
            parent=self,
            show_warning=self._show_warning,
            show_error=self._show_error,
            post_ui_task=self._post_ui_task,
            set_room_id=self._apply_auto_room_id,
            set_cookie=self._add_account_with_cookie,
            set_task_ids=self._apply_auto_task_ids,
            logger=logging.getLogger(__name__),
        )
        self._install_logging()
        self._refresh_account_list()
        self._restore_window_geometry()
        self._restore_shared_config()

        self._log_timer = QTimer(self)
        self._log_timer.setInterval(120)
        self._log_timer.timeout.connect(self._flush_log_queue)
        self._log_timer.start()

        self._stop_poll_timer = QTimer(self)
        self._stop_poll_timer.setInterval(120)
        self._stop_poll_timer.timeout.connect(self._poll_shutdown_all)

        self._config_sync_timer = QTimer(self)
        self._config_sync_timer.setInterval(2000)
        self._config_sync_timer.timeout.connect(self._sync_config_to_miners)

        self._task_refresh_timer = QTimer(self)
        self._task_refresh_timer.setSingleShot(True)
        self._task_refresh_timer.timeout.connect(self._schedule_task_refresh)

        self._watch_tick_timer = QTimer(self)
        self._watch_tick_timer.setInterval(1000)
        self._watch_tick_timer.timeout.connect(self._update_watch_estimate)

        QTimer.singleShot(3000, self._check_update_silent)

    # ---------- layout ----------

    def _build_layout(self) -> None:
        widgets = build_main_window_layout(
            self,
            MainWindowCallbacks(
                start=self.start_current_account,
                stop=self.stop_current_account,
                load_config=self.load_config,
                save_config=self.save_config,
                clear_logs=self.clear_logs,
                claim_rewards=self.claim_rewards,
                refresh_tasks=self.refresh_tasks,
                toggle_log=self._toggle_log,
                auto_fetch_room_id=self.auto_fetch_room_id,
                auto_fetch_task_ids_mode1=self.auto_fetch_task_ids_mode1,
                auto_fetch_task_ids_mode2=self.auto_fetch_task_ids_mode2,
                toggle_theme=self.toggle_theme,
            ),
        )
        self.account_panel = widgets.account_panel
        self.running_count_label = widgets.running_count_label
        self.rooms_edit = widgets.rooms_edit
        self.task_ids_edit = widgets.task_ids_edit
        self.notify_urls_edit = widgets.notify_urls_edit
        self.threads_spin = widgets.threads_spin
        self.reconnect_edit = widgets.reconnect_edit
        self.task_interval_edit = widgets.task_interval_edit
        self.verbose_check = widgets.verbose_check
        self.disable_task_notify_check = widgets.disable_task_notify_check
        self.progress_bar = widgets.progress_bar
        self.watch_info_label = widgets.watch_info_label
        self.task_progress_bar = widgets.task_progress_bar
        self.task_text = widgets.task_text
        self.log_text = widgets.log_text
        self.log_card = widgets.log_card
        self._log_toggle_btn = widgets.log_toggle_btn
        self.claim_rewards_btn = widgets.claim_rewards_btn
        self.auto_claim_rewards_check = widgets.auto_claim_rewards_check
        self.account_status_label = widgets.account_status_label
        self._log_expanded = False
        self._height_before_log: int | None = None

    def _connect_account_panel(self) -> None:
        panel = self.account_panel
        panel.account_selected.connect(self._on_account_selected)
        panel.add_via_qr.connect(self.qr_login_add_account)
        panel.add_via_clipboard.connect(self.add_account_via_clipboard)
        panel.add_via_browser.connect(self.auto_fetch_cookie)
        panel.remove_requested.connect(self.remove_account)
        panel.rename_requested.connect(self.rename_account)

    # ---------- theme ----------

    def toggle_theme(self) -> None:
        if self.theme_manager is not None:
            self.theme_manager.toggle()

    # ---------- local GUI state ----------

    def _restore_window_geometry(self) -> None:
        geometry = self._gui_state.value("main_window/geometry", None)
        if geometry is not None and self.restoreGeometry(geometry):
            return
        self._center_on_primary_screen()

    def _center_on_primary_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = available.left() + max(0, (available.width() - self.width()) // 2)
        y = available.top() + max(0, (available.height() - self.height()) // 2)
        self.move(x, y)

    # ---------- logging / cross-thread ----------

    def _install_logging(self) -> None:
        queue_handler = QueueLogHandler(self.log_queue)
        setup_logging(
            verbose=self.verbose_check.isChecked(),
            no_color=True,
            extra_handlers=[queue_handler],
        )

    def _post_ui_task(self, callback, *args, **kwargs) -> None:
        """线程安全地派发到 GUI 线程执行。"""
        if not self._ui_alive:
            return
        self.ui_call.emit(callback, args, kwargs)

    def _on_ui_call(self, fn, args, kwargs) -> None:
        if not self._ui_alive:
            return
        try:
            fn(*args, **kwargs)
        except Exception:
            logging.getLogger(__name__).exception("UI 任务执行失败")

    def _flush_log_queue(self) -> None:
        if not self._ui_alive:
            return
        changed = False
        while True:
            try:
                account_id, line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            changed = True
            if account_id:
                buffer = self._account_logs.setdefault(
                    account_id, deque(maxlen=LOG_BUFFER_SIZE)
                )
                buffer.append(line)
            else:
                self._system_logs.append(line)
        if changed:
            self._refresh_log_text()

        for account_id in list(self._task_refresh_pending):
            self._task_refresh_pending.discard(account_id)
            self.refresh_account_tasks(account_id, manual=False)

    # ---------- message helpers ----------

    def _show_info(self, title: str, msg: str) -> None:
        QMessageBox.information(self, title, msg)

    def _show_warning(self, title: str, msg: str) -> None:
        QMessageBox.warning(self, title, msg)

    def _show_error(self, title: str, msg: str) -> None:
        QMessageBox.critical(self, title, msg)

    # ---------- update check ----------

    def _check_update_silent(self) -> None:
        if not should_check_update(APP_VERSION, UPDATE_CHANNEL):
            return

        def _do() -> None:
            result = check_latest_release(
                app_version=APP_VERSION,
                update_channel=UPDATE_CHANNEL,
                latest_release_api=LATEST_RELEASE_API,
                releases_url=RELEASES_URL,
            )
            if result is None:
                return
            self._post_ui_task(
                self._show_update_available,
                result.latest_version,
                result.release_url,
            )

        threading.Thread(target=_do, daemon=True, name="gui-update-check").start()

    def _show_update_available(self, latest_version: str, release_url: str) -> None:
        if show_update_available_dialog(
            self,
            app_version=APP_VERSION,
            latest_version=latest_version,
            release_url=release_url,
        ):
            webbrowser.open(release_url)

    # ---------- shared config ----------

    def _build_shared_config(self) -> MinerConfig:
        return MinerConfig(
            cookie="",
            room_ids=parse_room_ids(self.rooms_edit.text().strip()),
            thread_count=int(self.threads_spin.value()),
            reconnect_delay_seconds=int(self.reconnect_edit.text().strip() or "8"),
            task_ids=parse_task_ids(self.task_ids_edit.text().strip()),
            task_query_interval_seconds=int(
                self.task_interval_edit.text().strip() or "30"
            ),
            notify_urls=parse_task_ids(self.notify_urls_edit.text().strip()),
            notify_on_task_complete=not self.disable_task_notify_check.isChecked(),
        )

    def _build_config_with_cookie(self, cookie: str) -> MinerConfig:
        config = self._build_shared_config()
        config.cookie = cookie
        return config

    # ---------- accounts ----------

    def _refresh_account_list(self) -> None:
        items = [
            AccountItemView(
                account_id=account.id,
                remark=account.remark or f"账号 {account.id[:8]}",
                running=self.miner_manager.is_running(account.id),
            )
            for account in self.account_store.list_accounts()
        ]
        self.account_panel.set_accounts(items)
        self._update_running_count()

    def _update_running_count(self) -> None:
        count = self.miner_manager.running_count()
        if count > 0:
            self.running_count_label.setText(f"已运行账号数量: {count}")
        else:
            self.running_count_label.setText("未运行任何账号")

    def _on_account_selected(self, account_id: str) -> None:
        self._current_account_id = account_id
        self._refresh_task_text()
        self._refresh_log_text()
        self._update_watch_estimate()
        account = self.account_store.get(account_id)
        if account is not None:
            running = self.miner_manager.is_running(account_id)
            state = "挂宝中" if running else "待机"
            self.account_status_label.setText(
                f"账号: {account.remark or account.id[:8]}（{state}）"
            )

    def _add_account_with_cookie(self, cookie: str) -> None:
        cookie = (cookie or "").strip()
        if not cookie:
            self._show_warning("添加账号", "Cookie 为空，无法添加账号。")
            return
        self._adding_accounts += 1

        def _do() -> None:
            uid: int | None = None
            uname = ""
            try:
                from overwatch_drops_miner.client import BilibiliClient
                import asyncio

                async def _query():
                    client = BilibiliClient(cookie)
                    try:
                        return await client.get_self_info()
                    finally:
                        await client.close()

                uid, uname = asyncio.run(_query()) or (None, "")
            except Exception as exc:
                LOGGER.warning("校验新账号 Cookie 失败: %s", exc)
                self._post_ui_task(
                    self._finish_add_account, cookie, "", False, str(exc)
                )
                return
            self._post_ui_task(self._finish_add_account, cookie, uname, uid is not None, "")

        threading.Thread(target=_do, daemon=True, name="account-add-validate").start()

    def _finish_add_account(
        self, cookie: str, uname: str, valid: bool, error: str
    ) -> None:
        self._adding_accounts = max(0, self._adding_accounts - 1)
        if not valid:
            self._show_warning(
                "添加账号失败",
                f"Cookie 校验未通过，账号未保存。\n{error}",
            )
            return
        remark = uname.strip() or f"账号 {len(self.account_store.list_accounts()) + 1}"
        account = self.account_store.add(cookie, remark=remark)
        self._account_logs.setdefault(account.id, deque(maxlen=LOG_BUFFER_SIZE))
        self._refresh_account_list()
        self.account_panel.select_account(account.id)
        LOGGER.info("账号 [%s] 已添加（凭据已加密保存）", remark)

    def qr_login_add_account(self) -> None:
        dialog = self._qr_login_dialog
        if dialog is not None and dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = QrLoginDialog(self, self._add_account_with_cookie)
        self._qr_login_dialog = dialog

        def clear_dialog(_result: int, current: QrLoginDialog = dialog) -> None:
            if self._qr_login_dialog is current:
                self._qr_login_dialog = None

        dialog.finished.connect(clear_dialog)
        dialog.show()
        dialog.start_session()

    def add_account_via_clipboard(self) -> None:
        dialog = TextInputDialog(
            self,
            "手动添加账号",
            "粘贴 Cookie（SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx）：",
            multiline=True,
            placeholder="SESSDATA=xxx; bili_jct=xxx; DedeUserID=xxx",
        )
        if dialog.exec() == QDialog.Accepted and dialog.text().strip():
            self._add_account_with_cookie(dialog.text())

    def auto_fetch_cookie(self) -> None:
        self.browser_actions.auto_fetch_cookie()

    def rename_account(self, account_id: str) -> None:
        account = self.account_store.get(account_id)
        if account is None:
            return
        dialog = TextInputDialog(
            self,
            "账号备注",
            "备注名：",
            initial_text=account.remark,
            placeholder="输入便于识别的备注名",
        )
        if dialog.exec() == QDialog.Accepted:
            self.account_store.update(account_id, remark=dialog.text())
            self._refresh_account_list()

    def remove_account(self, account_id: str) -> None:
        account = self.account_store.get(account_id)
        if account is None:
            return
        confirm = QMessageBox.question(
            self,
            "删除账号",
            f"确定删除账号 [{account.remark or account.id[:8]}] 吗？\n"
            "其本地加密凭据将一并删除。",
        )
        if confirm != QMessageBox.Yes:
            return
        if self.miner_manager.is_running(account_id):
            self.miner_manager.request_stop(account_id, logger=LOGGER)
        self.account_store.remove(account_id)
        self._account_logs.pop(account_id, None)
        self._task_controllers.pop(account_id, None)
        self._task_progress_results.pop(account_id, None)
        self._progress_values.pop(account_id, None)
        if self._current_account_id == account_id:
            self._current_account_id = None
            self.task_text.setPlainText("未选择账号")
            self.watch_info_label.setText("状态: 待机 | 本次有效观看: -- | 预计剩余: --")
            self.task_progress_bar.setValue(0)
        self._refresh_account_list()
        self._refresh_log_text()
        LOGGER.info("账号 [%s] 已删除", account.remark or account.id[:8])

    # ---------- start / stop ----------

    def start_account(self, account_id: str) -> None:
        account = self.account_store.get(account_id)
        if account is None:
            return
        if self.miner_manager.is_running(account_id):
            self._show_info("运行中", "该账号已在挂宝运行中。")
            return
        try:
            self._install_logging()
            config = self._build_config_with_cookie(account.cookie())
            config.validate()
        except Exception as exc:
            self._show_error("配置错误", str(exc))
            return
        if self.miner_manager.start(account, logger=LOGGER):
            self._finish_account_started(account, account_id)
            return
        # 启动失败通常是因为上次会话的线程残留（例如崩溃后未被清理）。
        # 先尝试轮询回收一次死线程，回收成功则立即重试启动。
        cleanup = self.miner_manager.poll_shutdown(account_id, logger=LOGGER)
        if cleanup == "stopped":
            if self.miner_manager.start(account, logger=LOGGER):
                self._finish_account_started(account, account_id)
                return
        self._show_warning(
            "启动失败",
            "该账号后台尚未完全停止，请稍候几秒后重试。",
        )

    def _finish_account_started(self, account: Account, account_id: str) -> None:
        """启动成功后的统一 UI 收尾：开启各计时器并刷新状态。"""
        LOGGER.info("账号 [%s] 挂宝已启动", account.remark or account.id[:8])
        self._start_progress_animation()
        self._config_sync_timer.start()
        self._stop_poll_timer.start()
        self._watch_tick_timer.start()
        self._schedule_task_refresh()
        self._update_running_count()
        self._on_account_selected(account_id)

    def stop_account(self, account_id: str) -> None:
        result = self.miner_manager.request_stop(account_id, logger=LOGGER)
        if result == "stopping_started":
            self._stop_poll_timer.start()

    def start_current_account(self) -> None:
        account_id = self.account_panel.current_account_id()
        if account_id is None:
            self._show_warning("无法启动", "请先在左侧添加并选择一个账号。")
            return
        self.start_account(account_id)

    def stop_current_account(self) -> None:
        account_id = self.account_panel.current_account_id()
        if account_id is None:
            return
        self.stop_account(account_id)

    def _on_account_state_thread(self, account_id: str, running: bool) -> None:
        self._post_ui_task(self._on_account_state_ui, account_id, running)

    def _on_account_state_ui(self, account_id: str, running: bool) -> None:
        # 账号已被删除时丢弃迟到的状态回调，避免界面出现幽灵条目。
        if not self._account_exists(account_id):
            return
        self.account_panel.set_running(account_id, running)
        self._update_running_count()
        if self._current_account_id == account_id:
            self._on_account_selected(account_id)
        if not running and self.miner_manager.running_count() == 0:
            self._stop_progress_animation()
            self._config_sync_timer.stop()
            self._watch_tick_timer.stop()

    def _poll_shutdown_all(self) -> None:
        # 对所有已注册账号逐个轮询：新契约下 poll_shutdown 对正常运行中的
        # 账号是安全的（不会误停），崩溃退出的死线程则会在轮询中被回收。
        states = self.miner_manager.shutdown_states()
        results = [
            self.miner_manager.poll_shutdown(account_id, logger=LOGGER)
            for account_id in states
        ]
        # 全部账号都已回收（no_thread）才停表；stopped 表示本轮刚完成一次
        # 清理，下一轮再确认；running 表示仍有活动线程。
        if not any(r in ("running", "stopped") for r in results):
            self._stop_poll_timer.stop()

    def _start_progress_animation(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(True)

    def _stop_progress_animation(self) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

    # ---------- watch estimate ----------

    def _update_watch_estimate(self) -> None:
        from overwatch_drops_miner.gui_parts.task_presenter import (
            format_watch_estimate,
        )

        account_id = self._current_account_id
        if account_id is None:
            self.watch_info_label.setText("状态: 待机 | 本次有效观看: -- | 预计剩余: --")
            self.task_progress_bar.setValue(0)
            return
        tracker = self.miner_manager.tracker(account_id)
        elapsed = tracker.elapsed_seconds() if tracker is not None else 0.0
        cur_value, limit_value = self._progress_values.get(account_id, (0.0, 0.0))
        running = self.miner_manager.is_running(account_id)
        self.watch_info_label.setText(
            format_watch_estimate(elapsed, cur_value, limit_value, running)
        )
        if limit_value > 0:
            percent = max(0, min(100, int(cur_value / limit_value * 100)))
            self.task_progress_bar.setValue(percent)
        else:
            self.task_progress_bar.setValue(0)

    # ---------- log / layout toggle ----------

    def _available_height(self) -> int:
        screen = QApplication.primaryScreen()
        if screen is None:
            return self._size_expanded[1]
        return screen.availableGeometry().height()

    def _toggle_log(self) -> None:
        if self._log_expanded:
            self.log_text.setVisible(False)
            self._log_toggle_btn.setText("▶ 运行日志")
            # 恢复到展开前记录的实际高度（兼容用户手动调整过的窗口大小），
            # 且不超过屏幕可用高度。
            restore_height = self._height_before_log or self._size_collapsed[1]
            self.resize(self.width(), min(restore_height, self._available_height()))
            self._height_before_log = None
        else:
            self._height_before_log = self.height()
            self.log_text.setVisible(True)
            self._log_toggle_btn.setText("▼ 运行日志")
            expanded_height = min(self._size_expanded[1], self._available_height())
            self.resize(self.width(), expanded_height)
        self._log_expanded = not self._log_expanded

    def clear_logs(self) -> None:
        account_id = self._current_account_id
        if account_id is not None:
            self._account_logs.get(account_id, deque()).clear()
        self._system_logs.clear()
        self._refresh_log_text()

    def _refresh_log_text(self) -> None:
        account_id = self._current_account_id
        account_lines = (
            self._account_logs.get(account_id, deque()) if account_id else deque()
        )
        lines = list(self._system_logs) + list(account_lines)
        scroll_bar = self.log_text.verticalScrollBar()
        scroll_value = scroll_bar.value()
        self.log_text.setPlainText("\n".join(lines))
        scroll_bar.setValue(min(scroll_value, scroll_bar.maximum()))

    # ---------- task progress ----------

    def _account_exists(self, account_id: str) -> bool:
        """校验账号仍存在，用于丢弃删除后迟到的后台回调。"""
        return self.account_store.get(account_id) is not None

    def _task_controller_for(self, account_id: str) -> TaskController:
        controller = self._task_controllers.get(account_id)
        if controller is not None:
            return controller

        def _cookie() -> str:
            current = self.account_store.get(account_id)
            if current is None:
                return ""
            try:
                return current.cookie()
            except OSError:
                return ""

        def _complete_refresh(result_text: str, rerun: bool) -> None:
            # 账号可能已在刷新期间被删除，迟到结果直接丢弃。
            if not self._account_exists(account_id):
                self._task_refresh_pending.discard(account_id)
                self._progress_values.pop(account_id, None)
                return
            self._set_task_progress_text(account_id, result_text)
            if rerun:
                self._task_refresh_pending.add(account_id)

        controller = TaskController(
            get_cookie=_cookie,
            get_room_ids=lambda: parse_room_ids(self.rooms_edit.text().strip()),
            get_task_ids=lambda: parse_task_ids(self.task_ids_edit.text().strip()),
            show_warning=self._show_warning,
            set_task_progress_text=lambda text, aid=account_id: self._set_task_progress_text(
                aid, text
            ),
            set_live_watch_time_text=lambda text: None,
            complete_task_refresh=_complete_refresh,
            post_ui_task=self._post_ui_task,
            get_auto_claim_enabled=lambda: self.auto_claim_rewards_check.isChecked(),
            on_progress_values=lambda cur, limit, aid=account_id: (
                self._progress_values.update({aid: (cur, limit)})
                if aid in self._task_controllers
                else None
            ),
        )
        self._task_controllers[account_id] = controller
        return controller

    def _set_task_progress_text(self, account_id: str, text: str) -> None:
        # 账号已被删除时丢弃迟到的任务结果，避免已删条目复活。
        if not self._account_exists(account_id):
            self._task_refresh_pending.discard(account_id)
            return
        self._task_progress_results[account_id] = text
        if self._current_account_id == account_id:
            self._refresh_task_text()

    def _refresh_task_text(self) -> None:
        account_id = self._current_account_id
        if account_id is None:
            self.task_text.setPlainText("未选择账号")
            return
        text = self._task_progress_results.get(account_id, "")
        self.task_text.setPlainText(text or "点击“手动刷新”查看任务进度")
        self._update_watch_estimate()

    def refresh_account_tasks(self, account_id: str, *, manual: bool = True) -> None:
        if not self.miner_manager.is_running(account_id):
            return
        controller = self._task_controller_for(account_id)
        controller.refresh(manual=manual)

    def refresh_tasks(self, *args, manual: bool = True, **kwargs) -> None:
        account_id = self.account_panel.current_account_id()
        if account_id is None:
            if manual:
                self._show_warning("提示", "请先选择账号")
            return
        self.refresh_account_tasks(account_id, manual=manual)

    def claim_rewards(self, *args, **kwargs) -> None:
        account_id = self.account_panel.current_account_id()
        if account_id is None:
            self._show_warning("提示", "请先选择账号")
            return
        controller = self._task_controller_for(account_id)
        controller.claim_rewards()

    def _schedule_task_refresh(self) -> None:
        running = self.miner_manager.shutdown_states()
        if not any(state == "running" for state in running.values()):
            return
        for account_id, state in running.items():
            if state == "running":
                self.refresh_account_tasks(account_id, manual=False)
        try:
            interval = int(self.task_interval_edit.text().strip() or "30")
        except ValueError:
            interval = 30
        self._task_refresh_timer.start(max(10, interval) * 1000)

    # ---------- browser actions passthrough ----------

    def _apply_auto_room_id(self, room_id: int) -> None:
        self.rooms_edit.setText(str(room_id))

    def _apply_auto_task_ids(self, task_ids_str: str) -> None:
        self.task_ids_edit.setText(task_ids_str)

    def auto_fetch_room_id(self) -> None:
        self.browser_actions.auto_fetch_room_id()

    def auto_fetch_task_ids_mode1(self) -> None:
        try:
            room_ids = parse_room_ids(self.rooms_edit.text().strip())
        except ValueError as exc:
            self._show_warning(
                "提示",
                f"{exc}。请修正后重试模式1，或使用自动获取模式2。",
            )
            return
        if not room_ids:
            self._show_warning(
                "提示",
                "自动获取模式1需要先填写有效的直播间号；也可使用自动获取模式2。",
            )
            return
        self.browser_actions.auto_fetch_task_ids_mode1(room_ids[0])

    def auto_fetch_task_ids_mode2(self) -> None:
        try:
            room_ids = parse_room_ids(self.rooms_edit.text().strip())
        except ValueError:
            room_ids = []
        self.browser_actions.auto_fetch_task_ids_mode2(
            room_id=room_ids[0] if room_ids else None
        )

    # ---------- config sync ----------

    def _sync_config_to_miners(self) -> None:
        miners = self.miner_manager.running_miners()
        if not miners:
            self._config_sync_timer.stop()
            return

        try:
            reconnect_val = int(self.reconnect_edit.text().strip() or "8")
        except ValueError:
            reconnect_val = None
        try:
            interval_val = int(self.task_interval_edit.text().strip() or "30")
        except ValueError:
            interval_val = None
        notify_on_task_complete = not self.disable_task_notify_check.isChecked()
        new_task_ids = parse_task_ids(self.task_ids_edit.text().strip())
        new_notify_urls = parse_task_ids(self.notify_urls_edit.text().strip())

        verbose = self.verbose_check.isChecked()
        for miner in miners:
            if reconnect_val is not None and reconnect_val > 0:
                miner.config.reconnect_delay_seconds = reconnect_val
            if interval_val is not None and interval_val > 0:
                miner.config.task_query_interval_seconds = interval_val
            miner.config.notify_on_task_complete = notify_on_task_complete
            if new_task_ids != miner.config.task_ids:
                miner.config.task_ids = new_task_ids
            if new_notify_urls != miner.config.notify_urls:
                miner.update_notifier(new_notify_urls)

    # ---------- close ----------

    def _save_session_state(self) -> None:
        self._gui_state.setValue(KEY_ROOMS, self.rooms_edit.text().strip())
        self._gui_state.setValue(KEY_NOTIFY_URLS, self.notify_urls_edit.text().strip())
        self._gui_state.setValue(KEY_THREAD_COUNT, self.threads_spin.value())
        self._gui_state.setValue(KEY_RECONNECT_DELAY, self.reconnect_edit.text().strip())
        self._gui_state.setValue(KEY_TASK_INTERVAL, self.task_interval_edit.text().strip())
        self._gui_state.setValue(KEY_VERBOSE, self.verbose_check.isChecked())
        self._gui_state.setValue(
            KEY_DISABLE_TASK_NOTIFY, self.disable_task_notify_check.isChecked()
        )
        self._gui_state.setValue(KEY_AUTO_CLAIM, self.auto_claim_rewards_check.isChecked())
        # 注意：任务 ID 不保存，重启后留空以便自动获取。
        self._gui_state.setValue("main_window/geometry", self.saveGeometry())
        self._gui_state.sync()

    def _restore_shared_config(self) -> None:
        rooms = str(self._gui_state.value(KEY_ROOMS, "") or "")
        if rooms:
            self.rooms_edit.setText(rooms)
        notify_urls = str(self._gui_state.value(KEY_NOTIFY_URLS, "") or "")
        if notify_urls:
            self.notify_urls_edit.setText(notify_urls)
        try:
            threads = int(str(self._gui_state.value(KEY_THREAD_COUNT, 1)))
        except (TypeError, ValueError):
            threads = 1
        self.threads_spin.setValue(max(1, min(128, threads)))
        reconnect = str(self._gui_state.value(KEY_RECONNECT_DELAY, "8") or "8")
        self.reconnect_edit.setText(reconnect)
        interval = str(self._gui_state.value(KEY_TASK_INTERVAL, "30") or "30")
        self.task_interval_edit.setText(interval)
        self.verbose_check.setChecked(_to_bool(self._gui_state.value(KEY_VERBOSE, False)))
        self.disable_task_notify_check.setChecked(
            _to_bool(self._gui_state.value(KEY_DISABLE_TASK_NOTIFY, False))
        )
        self.auto_claim_rewards_check.setChecked(
            _to_bool(self._gui_state.value(KEY_AUTO_CLAIM, False))
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        try:
            self._save_session_state()
        except Exception:
            logging.getLogger(__name__).exception("退出保存配置失败")
        dialog = self._qr_login_dialog
        if dialog is not None:
            dialog.cancel_session()
            dialog.close()
            self._qr_login_dialog = None
        self._ui_alive = False
        try:
            self.miner_manager.stop_all()
        except Exception:
            logging.getLogger(__name__).exception("关闭时停止挂宝失败")
        try:
            self.browser_actions.shutdown()
        except Exception:
            LOGGER.exception("关闭浏览器嗅探失败")
        # 渐进式关窗：给后台线程最多 5 秒优雅退出，期间不阻塞 GUI 线程。
        self._shutdown_deadline = time.monotonic() + 5.0
        QTimer.singleShot(200, self._close_poll_step)
        event.ignore()

    def _close_poll_step(self) -> None:
        """关窗轮询一步：所有账号线程均已回收或超时后才真正退出。"""
        results = [
            self.miner_manager.poll_shutdown(account_id, logger=LOGGER)
            for account_id in self.miner_manager.shutdown_states()
        ]
        if all(r == "no_thread" for r in results) or (
            time.monotonic() >= self._shutdown_deadline
        ):
            self._quit_app()
            return
        QTimer.singleShot(200, self._close_poll_step)

    def _quit_app(self) -> None:
        """最终退出：结束 Qt 事件循环。"""
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ---------- config load/save ----------

    def _apply_config_values(self, values: GuiConfigValues) -> None:
        # Cookie 来自账号栏凭据，配置文件中的 cookie 字段被忽略。
        self.rooms_edit.setText(values.rooms_text)
        try:
            self.threads_spin.setValue(max(1, min(128, int(values.thread_count_text))))
        except ValueError:
            pass
        self.reconnect_edit.setText(values.reconnect_delay_text)
        self.task_ids_edit.setText(values.task_ids_text)
        self.task_interval_edit.setText(values.task_query_interval_text)
        self.notify_urls_edit.setText(values.notify_urls_text)
        self.disable_task_notify_check.setChecked(not values.notify_on_task_complete)
        self.auto_claim_rewards_check.setChecked(values.auto_claim_rewards)
        self.verbose_check.setChecked(values.verbose)

    def _load_config_path(
        self,
        path: str | Path,
        *,
        show_error: bool,
    ) -> bool:
        try:
            values = values_from_config_data(load_config_data(path))
            self._apply_config_values(values)
            logging.getLogger(__name__).info("配置已加载: %s", path)
            return True
        except Exception as exc:
            if show_error:
                self._show_error("加载失败", str(exc))
            else:
                logging.getLogger(__name__).warning("加载配置失败: %s (%s)", path, exc)
            return False

    def load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "加载配置文件",
            "",
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return
        self._load_config_path(path, show_error=True)

    def save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存配置文件",
            "config.json",
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            config = self._build_shared_config()
            save_config_data(
                path,
                build_config_payload(
                    config,
                    verbose=self.verbose_check.isChecked(),
                    auto_claim_rewards=self.auto_claim_rewards_check.isChecked(),
                ),
            )
            logging.getLogger(__name__).info("配置已保存: %s", path)
        except Exception as exc:
            self._show_error("保存失败", str(exc))


def run_gui() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    configure_qt_app(app)
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "OverwatchDropsMiner.GUI.1"
        )
    except Exception:
        pass
    gui_state = GuiStateStore()
    theme_manager = ThemeManager(app, gui_state)
    window = MinerGUI(gui_state=gui_state, theme_manager=theme_manager)
    window.show()
    return app.exec()
