from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


def configure_qt_app(app: QApplication) -> None:
    app.setApplicationName("守望先锋直播掉宝助手")
    app.setOrganizationName("OverwatchDropsMiner")
    app.setStyle("Fusion")
    default_font = QFont("Segoe UI", 10)
    default_font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(default_font)
    # 全局样式表由 gui_parts.theme.ThemeManager 统一应用（深色/白天双主题）。
