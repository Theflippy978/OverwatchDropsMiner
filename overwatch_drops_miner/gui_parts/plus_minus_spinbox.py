from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRect, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
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

BUTTON_BG_PROPERTY = "ow_spin_btn_bg"
DEFAULT_BUTTON_BG = "#26334f"
BUTTON_BG_HOVER_PROPERTY = "ow_spin_btn_bg_hover"
DEFAULT_BUTTON_BG_HOVER = "#4c5e7d"
BUTTON_BORDER_PROPERTY = "ow_spin_btn_border"
DEFAULT_BUTTON_BORDER = "#4c5e7d"

# 加减号四臂长度（逻辑像素），横竖对称；按钮过小时自动收缩防溢出。
SYMBOL_ARM = 4.0

# 可视按钮方块相对命中条带（subControlRect）的内缩量：
# 让方块与输入框顶/底边线及彼此之间保持留白，不再贴合重合。
BUTTON_INSET = 3


def _button_inner_rect(rect: QRect) -> QRect:
    """命中条带内缩后的可视按钮方块。"""
    return rect.adjusted(
        BUTTON_INSET, BUTTON_INSET, -BUTTON_INSET, -BUTTON_INSET
    )


def _symbol_arm(rect: QRect) -> float:
    """按按钮矩形收缩臂长：线段含 2px 笔宽需完整落在按钮内。

    矩形半边长 half = min(w, h) / 2，笔迹外缘为 arm + 1，
    故 arm ≤ half - 1.5 时四周仍各留约 0.5px 余量。
    """
    half = min(rect.width(), rect.height()) / 2.0
    return max(2.0, min(SYMBOL_ARM, half - 1.5))


def _symbol_center(rect: QRect) -> QPointF:
    """按钮矩形的绘制语义中心（浮点，与 drawRoundedRect 对齐）。

    符号必须居中于 paintEvent 里 drawRoundedRect(inner) 画出的可视
    方块。Qt 的绘制 API 按「连续区间」解释 QRect：方块覆盖
    [left, left+width] × [top, top+height]，其中心是
    (left + width/2, top + height/2)。

    不能用另外两种算法：
    - QRect.center()（整数）：偶数宽高时截断偏左上半像素；
    - ((left+right)/2, (top+bottom)/2)：像素包含式语义，right/bottom
      比绘制边界小 1，同样恒定偏左上半像素（175%~200% DPI 下放大
      为可见错位，自绘方块参照显形后暴露）。
    """
    return QPointF(
        rect.left() + rect.width() / 2.0,
        rect.top() + rect.height() / 2.0,
    )


def _minus_line(rect: QRect) -> QLineF:
    """减号水平线段：关于按钮面积中心左右对称。"""
    c = _symbol_center(rect)
    arm = _symbol_arm(rect)
    return QLineF(c.x() - arm, c.y(), c.x() + arm, c.y())


def _plus_lines(rect: QRect) -> tuple[QLineF, QLineF]:
    """加号横竖两条线段：交点即按钮面积中心。"""
    c = _symbol_center(rect)
    arm = _symbol_arm(rect)
    horizontal = QLineF(c.x() - arm, c.y(), c.x() + arm, c.y())
    vertical = QLineF(c.x(), c.y() - arm, c.x(), c.y() + arm)
    return horizontal, vertical


class PlusMinusSpinBox(QSpinBox):
    """QSpinBox with crisp +/− symbols painted on the up/down buttons.

    The clickable areas are the transparent sub-control strips laid out
    by the stylesheet; the visible rounded squares are painted here with
    an inset so they keep clear of the frame edges and of each other.
    Symbols take their color from the active theme (set by ThemeManager
    via application properties) so they stay visible in both dark and
    light modes; hovering a button brightens it.
    """

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        app = QApplication.instance()
        color = QColor(
            str(app.property(SYMBOL_COLOR_PROPERTY) or DEFAULT_SYMBOL_COLOR)
        )
        hover_color = QColor(
            str(app.property(HOVER_SYMBOL_COLOR_PROPERTY) or DEFAULT_HOVER_COLOR)
        )
        btn_bg = QColor(
            str(app.property(BUTTON_BG_PROPERTY) or DEFAULT_BUTTON_BG)
        )
        btn_bg_hover = QColor(
            str(app.property(BUTTON_BG_HOVER_PROPERTY) or DEFAULT_BUTTON_BG_HOVER)
        )
        btn_border = QColor(
            str(app.property(BUTTON_BORDER_PROPERTY) or DEFAULT_BUTTON_BORDER)
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
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 两个按钮的 hover 高亮行为对称：悬停哪个按钮，哪个按钮变亮。
        up_hover = mouse_over and bool(
            option.activeSubControls & QStyle.SC_SpinBoxUp
        )
        down_hover = mouse_over and bool(
            option.activeSubControls & QStyle.SC_SpinBoxDown
        )

        for rect, hovered in ((up_rect, up_hover), (down_rect, down_hover)):
            inner = _button_inner_rect(rect)
            if inner.isEmpty():
                continue
            painter.setPen(QPen(btn_border, 1))
            painter.setBrush(QBrush(btn_bg_hover if hovered else btn_bg))
            painter.drawRoundedRect(inner, 4, 4)

        def symbol_pen(bright: bool) -> QPen:
            pen = QPen(hover_color if bright else color)
            pen.setWidth(2)
            pen.setCapStyle(Qt.FlatCap)
            return pen

        painter.setPen(symbol_pen(down_hover))
        painter.drawLine(_minus_line(_button_inner_rect(down_rect)))
        painter.setPen(symbol_pen(up_hover))
        for line in _plus_lines(_button_inner_rect(up_rect)):
            painter.drawLine(line)
