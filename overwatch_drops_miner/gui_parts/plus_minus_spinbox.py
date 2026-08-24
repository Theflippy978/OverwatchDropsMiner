from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
)

SYMBOL_COLOR_PROPERTY = "ow_spin_symbol_color"
DEFAULT_SYMBOL_COLOR = "#94a3b8"
HOVER_SYMBOL_COLOR_PROPERTY = "ow_spin_symbol_hover_color"
DEFAULT_HOVER_COLOR = "#f8fafc"


class PlusMinusSpinBox(QSpinBox):
    """QSpinBox with crisp +/− symbols painted on the up/down buttons.

    The symbols take their color from the active theme (set by ThemeManager
    via application properties) so they stay visible in both dark and light
    modes; hovering a button brightens its symbol.
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        app = QApplication.instance()
        color = str(
            app.property(SYMBOL_COLOR_PROPERTY) or DEFAULT_SYMBOL_COLOR
        )
        hover_color = str(
            app.property(HOVER_SYMBOL_COLOR_PROPERTY) or DEFAULT_HOVER_COLOR
        )

        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        style = self.style()
        up_rect = style.subControlRect(
            QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxUp, self
        )
        down_rect = style.subControlRect(
            QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self
        )
        mouse_over = bool(option.state & QStyle.State_MouseOver)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor(color))
        pen.setWidth(2)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        self._draw_minus(painter, down_rect)
        if mouse_over and (option.activeSubControls & QStyle.SC_SpinBoxUp):
            pen.setColor(QColor(hover_color))
            painter.setPen(pen)
        self._draw_plus(painter, up_rect)

    def _draw_plus(self, painter: QPainter, rect: QRect) -> None:
        cx = rect.center().x()
        cy = rect.center().y()
        arm = 4
        painter.drawLine(cx - arm, cy, cx + arm, cy)
        painter.drawLine(cx, cy - arm, cx, cy + arm)

    def _draw_minus(self, painter: QPainter, rect: QRect) -> None:
        cx = rect.center().x()
        cy = rect.center().y()
        arm = 4
        painter.drawLine(cx - arm, cy, cx + arm, cy)
