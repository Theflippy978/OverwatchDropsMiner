from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRect, Qt
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

# 加减号四臂长度（逻辑像素），横竖对称。
SYMBOL_ARM = 4.0


def _symbol_center(rect: QRect) -> QPointF:
    """按钮矩形覆盖面积的精确几何中心（浮点，单位：逻辑像素）。

    QRect.center() 返回整数坐标：当矩形宽或高为偶数时真实中心落在
    半像素位置，整数截断会让结果偏向左上（例如 QRect(106, 2, 16, 12)
    的真实中心是 (113.5, 7.5)，而 center() 返回 (113, 7)）。该半像素
    偏差在高 DPI（125%~200% 缩放）下被放大为肉眼可见的错位。
    像素 i 的覆盖面积为 [i-0.5, i+0.5]，故面积中心为
    ((left+right)/2, (top+bottom)/2)。注意不可用 QRectF(rect).center()
    代替：QRect→QRectF 转换会把右/下边界外扩 1，同样产生偏差。
    """
    return QPointF(
        (rect.left() + rect.right()) / 2.0,
        (rect.top() + rect.bottom()) / 2.0,
    )


def _minus_line(rect: QRect) -> QLineF:
    """减号水平线段：关于按钮面积中心左右对称。"""
    c = _symbol_center(rect)
    arm = SYMBOL_ARM
    return QLineF(c.x() - arm, c.y(), c.x() + arm, c.y())


def _plus_lines(rect: QRect) -> tuple[QLineF, QLineF]:
    """加号横竖两条线段：交点即按钮面积中心。"""
    c = _symbol_center(rect)
    arm = SYMBOL_ARM
    horizontal = QLineF(c.x() - arm, c.y(), c.x() + arm, c.y())
    vertical = QLineF(c.x(), c.y() - arm, c.x(), c.y() + arm)
    return horizontal, vertical


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
        ).adjusted(2, 2, -2, -2)
        down_rect = style.subControlRect(
            QStyle.CC_SpinBox, option, QStyle.SC_SpinBoxDown, self
        ).adjusted(2, 2, -2, -2)
        mouse_over = bool(option.state & QStyle.State_MouseOver)

        painter = QPainter(self)
        # 抗锯齿 + 浮点线段坐标：符号围绕真实几何中心对称栅格化，
        # 高 DPI 下不再因整数取整偏向左上（见 _symbol_center 注释）。
        painter.setRenderHint(QPainter.Antialiasing, True)

        def symbol_pen(bright: bool) -> QPen:
            pen = QPen(QColor(hover_color if bright else color))
            pen.setWidth(2)
            pen.setCapStyle(Qt.FlatCap)
            return pen

        # 两个按钮的 hover 高亮行为对称：悬停哪个按钮，哪个按钮的符号变亮
        up_hover = mouse_over and bool(option.activeSubControls & QStyle.SC_SpinBoxUp)
        down_hover = mouse_over and bool(
            option.activeSubControls & QStyle.SC_SpinBoxDown
        )
        painter.setPen(symbol_pen(down_hover))
        painter.drawLine(_minus_line(down_rect))
        painter.setPen(symbol_pen(up_hover))
        for line in _plus_lines(up_rect):
            painter.drawLine(line)
