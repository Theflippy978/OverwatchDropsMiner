from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from overwatch_drops_miner.gui_parts.styles import make_button


@dataclass(slots=True)
class AccountItemView:
    account_id: str
    remark: str
    running: bool = False


class AccountPanel(QFrame):
    """左侧多账号栏：账号列表 + 添加/启停/备注/删除操作。"""

    account_selected = Signal(str)
    add_via_qr = Signal()
    add_via_clipboard = Signal()
    add_via_browser = Signal()
    remove_requested = Signal(str)
    rename_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.setFixedWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("账号")
        title.setObjectName("panelTitle")
        self._count_label = QLabel("0 个")
        self._count_label.setObjectName("dimLabel")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._count_label)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list_widget, 1)

        self.add_button = make_button("添加账号", "primary", self._show_add_menu)
        layout.addWidget(self.add_button)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.rename_button = make_button("备注", "neutral", self._emit_rename)
        self.remove_button = make_button("删除", "danger-outline", self._emit_remove)
        action_row.addWidget(self.rename_button, 1)
        action_row.addWidget(self.remove_button, 1)
        layout.addLayout(action_row)

        self._add_menu = QMenu(self)
        self._add_menu.addAction("扫码登录", self.add_via_qr.emit)
        self._add_menu.addAction("手动粘贴 Cookie", self.add_via_clipboard.emit)
        self._add_menu.addAction("浏览器自动捕获", self.add_via_browser.emit)

        self._account_ids: list[str] = []

    # ---------- public API ----------

    def set_accounts(self, items: list[AccountItemView]) -> None:
        previous = self.current_account_id()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self._account_ids = []
        for item in items:
            self._account_ids.append(item.account_id)
            widget_item = QListWidgetItem(item.remark or f"账号 {item.account_id[:8]}")
            widget_item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            if item.running:
                widget_item.setForeground(QColor("#22c55e"))
                widget_item.setToolTip("运行中")
            else:
                widget_item.setToolTip("未运行")
            self.list_widget.addItem(widget_item)
        self.list_widget.blockSignals(False)
        self._count_label.setText(f"{len(items)} 个")

        if previous and previous in self._account_ids:
            self.select_account(previous)
        elif items:
            self.list_widget.setCurrentRow(0)
        else:
            self._update_action_buttons(None)

    def select_account(self, account_id: str) -> None:
        row = self._account_ids.index(account_id) if account_id in self._account_ids else -1
        if row >= 0:
            self.list_widget.setCurrentRow(row)

    def current_account_id(self) -> str | None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self._account_ids):
            return self._account_ids[row]
        return None

    def set_running(self, account_id: str, running: bool) -> None:
        row = (
            self._account_ids.index(account_id)
            if account_id in self._account_ids
            else -1
        )
        if row < 0:
            return
        if running:
            self.list_widget.item(row).setForeground(QColor("#22c55e"))
            self.list_widget.item(row).setToolTip("运行中")
        else:
            self.list_widget.item(row).setToolTip("未运行")

    # ---------- internals ----------

    def _show_add_menu(self) -> None:
        # 弹出到按钮正上方，避免被窗口底部截断。
        top_left = self.add_button.mapToGlobal(self.add_button.rect().topLeft())
        menu_height = self._add_menu.sizeHint().height()
        self._add_menu.exec(top_left - QPoint(0, menu_height + 4))

    def _on_current_changed(self, current: QListWidgetItem, _previous) -> None:
        account_id = self.current_account_id()
        if account_id:
            self._update_action_buttons(account_id)
            self.account_selected.emit(account_id)

    def _emit_rename(self) -> None:
        account_id = self.current_account_id()
        if account_id:
            self.rename_requested.emit(account_id)

    def _emit_remove(self) -> None:
        account_id = self.current_account_id()
        if account_id:
            self.remove_requested.emit(account_id)

    def _update_action_buttons(self, account_id: str | None) -> None:
        has_account = account_id is not None
        self.rename_button.setEnabled(has_account)
        self.remove_button.setEnabled(has_account)
