from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from overwatch_drops_miner.gui_parts.app_style import configure_qt_app
from overwatch_drops_miner.gui_parts.plus_minus_spinbox import (
    SYMBOL_ARM,
    PlusMinusSpinBox,
    _minus_line,
    _plus_lines,
    _symbol_center,
)


class SymbolGeometryTest(unittest.TestCase):
    """加减号符号浮点几何回归测试。

    背景：符号位置曾用 QRect.center()（整数坐标）计算，偶数宽高的
    按钮矩形真实中心落在半像素处，整数截断使 +/− 整体偏向左上半个
    逻辑像素，在高 DPI（175%/200%）下放大为明显错位。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_qt_app(cls.app)

    def test_center_is_exact_area_center(self) -> None:
        # 覆盖奇偶宽高组合；期望值即 ((left+right)/2, (top+bottom)/2)。
        cases = [
            (106, 2, 16, 12),   # 离屏实测的默认按钮矩形（曾偏到 (113,7)）
            (0, 0, 16, 16),
            (3, 5, 8, 9),
            (0, 0, 19, 17),
            (104, 17, 20, 14),
        ]
        for left, top, width, height in cases:
            with self.subTest(rect=(left, top, width, height)):
                rect = QRect(left, top, width, height)
                center = _symbol_center(rect)
                self.assertEqual(
                    center.x(),
                    (rect.left() + rect.right()) / 2.0,
                )
                self.assertEqual(
                    center.y(),
                    (rect.top() + rect.bottom()) / 2.0,
                )

    def test_center_avoids_legacy_integer_truncation(self) -> None:
        # 回归锚点：QRect(106,2,16,12) 的整数 center() 是 (113,7)，
        # 偏离真实中心 (113.5, 7.5)；新实现必须给出精确值。
        rect = QRect(106, 2, 16, 12)
        legacy = rect.center()
        if (legacy.x(), legacy.y()) == (113.5, 7.5):
            self.skipTest("当前 Qt 版本 center() 未截断，锚点不适用")
        self.assertNotEqual(
            (_symbol_center(rect).x(), _symbol_center(rect).y()),
            (legacy.x(), legacy.y()),
        )
        self.assertEqual(_symbol_center(rect).x(), 113.5)
        self.assertEqual(_symbol_center(rect).y(), 7.5)

    def test_plus_lines_symmetric_around_center(self) -> None:
        rect = QRect(104, 0, 20, 16)
        horizontal, vertical = _plus_lines(rect)
        center = _symbol_center(rect)

        self.assertAlmostEqual(horizontal.y1(), center.y())
        self.assertAlmostEqual(horizontal.y2(), center.y())
        self.assertAlmostEqual(horizontal.x1(), center.x() - SYMBOL_ARM)
        self.assertAlmostEqual(horizontal.x2(), center.x() + SYMBOL_ARM)

        self.assertAlmostEqual(vertical.x1(), center.x())
        self.assertAlmostEqual(vertical.x2(), center.x())
        self.assertAlmostEqual(vertical.y1(), center.y() - SYMBOL_ARM)
        self.assertAlmostEqual(vertical.y2(), center.y() + SYMBOL_ARM)

        # 左右臂、上下臂长度严格相等（对称性）。
        self.assertAlmostEqual(
            center.x() - horizontal.x1(), horizontal.x2() - center.x()
        )
        self.assertAlmostEqual(
            center.y() - vertical.y1(), vertical.y2() - center.y()
        )

    def test_minus_line_is_horizontal_through_center(self) -> None:
        rect = QRect(104, 17, 20, 16)
        line = _minus_line(rect)
        center = _symbol_center(rect)

        self.assertAlmostEqual(line.y1(), center.y())
        self.assertAlmostEqual(line.y2(), center.y())
        self.assertAlmostEqual(line.x1(), center.x() - SYMBOL_ARM)
        self.assertAlmostEqual(line.x2(), center.x() + SYMBOL_ARM)


class PaintSmokeTest(unittest.TestCase):
    """paintEvent 冒烟：双主题颜色属性下均可正常绘制出符号内容。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        configure_qt_app(cls.app)

    def _render_widget(self) -> QImage:
        spin = PlusMinusSpinBox()
        spin.setRange(1, 16)
        spin.setValue(1)
        spin.resize(spin.sizeHint())
        spin.show()
        self.app.processEvents()

        image = QImage(spin.size(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        spin.render(image)
        self.app.processEvents()
        spin.hide()
        return image

    @staticmethod
    def _non_transparent_pixels(image: QImage) -> int:
        count = 0
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixel(x, y) != 0:
                    count += 1
        return count

    def test_paint_produces_content_in_both_themes(self) -> None:
        theme_colors = {
            "dark": ("#94a3b8", "#f8fafc"),
            "light": ("#64748b", "#0f172a"),
        }
        for name, (symbol_color, hover_color) in theme_colors.items():
            with self.subTest(theme=name):
                app = self.app
                app.setProperty("ow_spin_symbol_color", symbol_color)
                app.setProperty("ow_spin_symbol_hover_color", hover_color)
                try:
                    image = self._render_widget()
                finally:
                    app.setProperty("ow_spin_symbol_color", None)
                    app.setProperty("ow_spin_symbol_hover_color", None)
                self.assertGreater(self._non_transparent_pixels(image), 0)


if __name__ == "__main__":
    unittest.main()
