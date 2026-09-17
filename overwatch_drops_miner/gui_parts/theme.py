from __future__ import annotations

import winreg
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from overwatch_drops_miner.gui_parts.gui_state import GuiStateStore

THEME_KEY = "ui/theme"
DARK = "dark"
LIGHT = "light"

# 系统深浅色轮询间隔：轻量读注册表，5 秒足够灵敏且几乎无开销。
SYSTEM_THEME_POLL_INTERVAL_MS = 5000

_SYSTEM_LIGHT_THEME_REG_PATH = (
    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
)
_SYSTEM_LIGHT_THEME_VALUE = "AppsUseLightTheme"


class ThemeTokens:
    __slots__ = (
        "name",
        "bg",
        "card",
        "input_bg",
        "input_border",
        "text",
        "text_dim",
        "border",
        "hover",
        "tooltip_bg",
        "tooltip_border",
        "menu_bg",
        "scrollbar",
        "scrollbar_hover",
        "selection",
        "accent",
        "accent_hover",
        "accent_pressed",
        "success",
        "success_hover",
        "success_pressed",
        "danger",
        "danger_hover",
        "danger_pressed",
        "purple",
        "purple_hover",
        "purple_pressed",
        "neutral",
        "neutral_hover",
        "neutral_pressed",
        "neutral_border",
        "neutral_border_hover",
        "status_ok",
        "status_warn",
        "status_error",
        "status_idle",
    )

    def __init__(self, **tokens) -> None:
        for slot in self.__slots__:
            setattr(self, slot, tokens[slot])


_DARK_TOKENS = ThemeTokens(
    name=DARK,
    bg="#0f172a",
    card="#1b2336",
    input_bg="#24304a",
    input_border="#334155",
    text="#f8fafc",
    text_dim="#94a3b8",
    border="#334155",
    hover="#26334f",
    tooltip_bg="#1e293b",
    tooltip_border="#3b4a63",
    menu_bg="#1e293b",
    scrollbar="#3b4a63",
    scrollbar_hover="#4c5e7d",
    selection="#3b82f6",
    accent="#3b82f6",
    accent_hover="#2f6fe0",
    accent_pressed="#2559bd",
    success="#22c55e",
    success_hover="#1caf52",
    success_pressed="#178f43",
    danger="#ef4444",
    danger_hover="#dc3535",
    danger_pressed="#b92828",
    purple="#a78bfa",
    purple_hover="#9272f0",
    purple_pressed="#7a58d8",
    neutral="#27324a",
    neutral_hover="#314060",
    neutral_pressed="#1e2740",
    neutral_border="#3b4a63",
    neutral_border_hover="#4c5e7d",
    status_ok="#4ade80",
    status_warn="#fbbf24",
    status_error="#f87171",
    status_idle="#94a3b8",
)

_LIGHT_TOKENS = ThemeTokens(
    name=LIGHT,
    bg="#f1f5f9",
    card="#ffffff",
    input_bg="#f8fafc",
    input_border="#cbd5e1",
    text="#0f172a",
    text_dim="#64748b",
    border="#cbd5e1",
    hover="#e8eef5",
    tooltip_bg="#ffffff",
    tooltip_border="#94a3b8",
    menu_bg="#ffffff",
    scrollbar="#cbd5e1",
    scrollbar_hover="#94a3b8",
    selection="#3b82f6",
    accent="#2563eb",
    accent_hover="#1d4fd8",
    accent_pressed="#1a41b8",
    success="#16a34a",
    success_hover="#128a3f",
    success_pressed="#0f7334",
    danger="#dc2626",
    danger_hover="#c41f1f",
    danger_pressed="#a31a1a",
    purple="#7c3aed",
    purple_hover="#6b2fd4",
    purple_pressed="#5a26b3",
    neutral="#e8eef5",
    neutral_hover="#dbe5ef",
    neutral_pressed="#cdd9e6",
    neutral_border="#cbd5e1",
    neutral_border_hover="#94a3b8",
    status_ok="#16a34a",
    status_warn="#d97706",
    status_error="#dc2626",
    status_idle="#64748b",
)

TOKENS = {DARK: _DARK_TOKENS, LIGHT: _LIGHT_TOKENS}


def detect_system_theme() -> str:
    """Return the Windows global apps theme; dark when unavailable."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _SYSTEM_LIGHT_THEME_REG_PATH
        ) as key:
            value, _ = winreg.QueryValueEx(key, _SYSTEM_LIGHT_THEME_VALUE)
        return LIGHT if int(value) else DARK
    except Exception:
        return DARK


def build_stylesheet(t: ThemeTokens) -> str:
    button_common = (
        "border:0;border-radius:6px;padding:8px 18px;min-height:20px;"
        "font-weight:600;"
    )
    neutral_button = (
        f"QPushButton[accent=\"neutral\"]{{background:{t.neutral};color:{t.text};"
        f"border:1px solid {t.neutral_border};{button_common}font-weight:500;}}"
        f"QPushButton[accent=\"neutral\"]:hover{{background:{t.neutral_hover};"
        f"border-color:{t.neutral_border_hover};}}"
        f"QPushButton[accent=\"neutral\"]:pressed{{background:{t.neutral_pressed};}}"
    )
    outline_danger_button = (
        f"QPushButton[accent=\"danger-outline\"]{{background:transparent;color:{t.danger};"
        f"border:1px solid {t.danger};border-radius:6px;padding:8px 18px;"
        "min-height:20px;font-weight:600;}"
        f"QPushButton[accent=\"danger-outline\"]:hover{{background:{t.danger};color:#ffffff;}}"
        f"QPushButton[accent=\"danger-outline\"]:pressed{{background:{t.danger_pressed};color:#ffffff;}}"
    )
    return f"""
        QWidget {{ background: {t.bg}; color: {t.text}; }}
        QLabel {{ background: transparent; color: {t.text}; }}
        QLabel#dimLabel {{ color: {t.text_dim}; }}
        QLabel#panelTitle {{ color: {t.text}; font-weight: 600; }}
        QFrame#card {{ background: {t.card}; border: 1px solid {t.border}; border-radius: 10px; }}
        QFrame#hline {{ background: {t.border}; max-height: 1px; border: 0; }}

        QToolTip {{ background: {t.tooltip_bg}; color: {t.text};
                   border: 1px solid {t.tooltip_border};
                   padding: 6px 10px; border-radius: 6px; }}

        QLineEdit {{
            background: {t.input_bg}; color: {t.text};
            border: 1px solid {t.input_border}; border-radius: 6px;
            padding: 6px 10px; min-height: 20px;
            selection-background-color: {t.selection};
        }}
        QLineEdit:focus {{ border-color: {t.accent}; }}
        QLineEdit:disabled {{ color: {t.text_dim}; background: {t.hover}; }}

        QSpinBox {{
            background: {t.input_bg}; color: {t.text};
            border: 1px solid {t.input_border}; border-radius: 6px;
            padding: 4px 8px; min-height: 20px; min-width: 64px;
        }}
        QSpinBox:focus {{ border-color: {t.accent}; }}
        QSpinBox::up-button, QSpinBox::down-button {{
            /* 按钮可视外观由 PlusMinusSpinBox.paintEvent 自绘（可在命中条带
               内自由内缩，与输入框顶/底边及彼此之间保持留白）；此处仅保留
               透明命中条带，宽度和上下两段划分仍由 Qt 布局提供 */
            background: transparent; border: 0;
            width: 20px;
        }}
        QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; }}
        QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; }}
        QSpinBox::up-arrow {{ width: 0; height: 0; }}
        QSpinBox::down-arrow {{ width: 0; height: 0; }}

        QPlainTextEdit {{
            background: {t.input_bg}; color: {t.text};
            border: 1px solid {t.input_border}; border-radius: 6px;
            padding: 6px; selection-background-color: {t.selection};
        }}

        QListWidget {{
            background: {t.input_bg}; color: {t.text};
            border: 1px solid {t.input_border}; border-radius: 8px;
            padding: 4px; outline: 0;
        }}
        QListWidget::item {{ border-radius: 6px; padding: 8px 10px; margin: 2px 1px; }}
        QListWidget::item:hover {{ background: {t.hover}; }}
        QListWidget::item:selected {{ background: {t.accent}; color: #ffffff; }}

        QCheckBox {{ background: transparent; spacing: 8px; color: {t.text}; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px; border: 1px solid {t.neutral_border_hover};
            border-radius: 4px; background: {t.input_bg};
        }}
        QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
        QCheckBox::indicator:checked {{
            background: {t.accent}; border-color: {t.accent}; image: none;
        }}

        QProgressBar {{
            background: {t.input_bg}; border: 0; border-radius: 4px;
            min-height: 6px; max-height: 6px;
        }}
        QProgressBar::chunk {{
            background: {t.accent};
            border-radius: 4px;
        }}

        QProgressBar#taskProgress {{
            background: {t.input_bg}; border: 1px solid {t.border};
            border-radius: 8px; min-height: 20px; max-height: 20px;
            color: {t.text}; font-weight: 600; text-align: center;
            padding: 0 10px;
        }}
        QProgressBar#taskProgress::chunk {{
            background: {t.accent};
            border-radius: 7px;
        }}

        QPushButton[accent="primary"] {{ background: {t.accent}; color: #ffffff; {button_common} }}
        QPushButton[accent="primary"]:hover {{ background: {t.accent_hover}; }}
        QPushButton[accent="primary"]:pressed {{ background: {t.accent_pressed}; }}
        QPushButton[accent="success"] {{ background: {t.success}; color: #ffffff; {button_common} }}
        QPushButton[accent="success"]:hover {{ background: {t.success_hover}; }}
        QPushButton[accent="success"]:pressed {{ background: {t.success_pressed}; }}
        QPushButton[accent="danger"] {{ background: {t.danger}; color: #ffffff; {button_common} }}
        QPushButton[accent="danger"]:hover {{ background: {t.danger_hover}; }}
        QPushButton[accent="danger"]:pressed {{ background: {t.danger_pressed}; }}
        QPushButton[accent="purple"] {{ background: {t.purple}; color: #ffffff; {button_common} }}
        QPushButton[accent="purple"]:hover {{ background: {t.purple_hover}; }}
        QPushButton[accent="purple"]:pressed {{ background: {t.purple_pressed}; }}
        {neutral_button}
        {outline_danger_button}
        QPushButton[accent="ghost"] {{
            background: transparent; color: {t.text_dim}; border: 0;
            border-radius: 6px; padding: 8px 18px; min-height: 20px; font-weight: 600;
        }}
        QPushButton[accent="ghost"]:hover {{ background: {t.hover}; color: {t.accent}; }}

        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{
            background: {t.scrollbar}; border-radius: 4px; min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {t.scrollbar_hover}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            background: transparent; height: 0; border: 0;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
        QScrollBar::handle:horizontal {{
            background: {t.scrollbar}; border-radius: 4px; min-width: 24px;
        }}
        QScrollBar::handle:horizontal:hover {{ background: {t.scrollbar_hover}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            background: transparent; width: 0; border: 0;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

        QMenu {{
            background: {t.menu_bg}; color: {t.text};
            border: 1px solid {t.border}; border-radius: 8px; padding: 4px;
        }}
        QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {t.accent}; color: #ffffff; }}

        QMessageBox {{ background: {t.card}; }}
        QMessageBox QLabel {{ color: {t.text}; }}
        QMessageBox QPushButton {{
            background: {t.neutral}; color: {t.text};
            border: 1px solid {t.neutral_border}; border-radius: 6px;
            padding: 6px 20px; min-height: 20px; font-weight: 500;
        }}
        QMessageBox QPushButton:hover {{ background: {t.neutral_hover}; }}

        QDialog {{ background: {t.card}; }}
    """


class ThemeManager(QObject):
    """Owns the active theme; applies full-app QSS and persists the choice."""

    def __init__(
        self,
        app: QApplication,
        gui_state: GuiStateStore,
        *,
        system_theme_reader: Callable[[], str] | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._gui_state = gui_state
        # 系统主题读取器可注入，便于单元测试模拟注册表深浅色变化。
        self._system_theme_reader = system_theme_reader or detect_system_theme
        detected = self._system_theme_reader()
        saved = str(gui_state.value(THEME_KEY, "") or "").strip()
        if saved in TOKENS:
            self._theme = saved
        else:
            self._theme = detected
        # 记录最近一次观测到的系统主题，供运行中轮询检测切换。
        self._last_system_theme = detected
        self._poll_timer: QTimer | None = None
        self._apply()

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def tokens(self) -> ThemeTokens:
        return TOKENS[self._theme]

    def is_dark(self) -> bool:
        return self._theme == DARK

    def set_theme(self, theme: str) -> None:
        if theme not in TOKENS or theme == self._theme:
            return
        self._theme = theme
        self._apply()
        self._gui_state.setValue(THEME_KEY, theme)
        self._gui_state.sync()

    def toggle(self) -> None:
        self.set_theme(LIGHT if self._theme == DARK else DARK)

    def check_system_theme_changed(self) -> bool:
        """检查 Windows 系统深浅色是否切换。

        与上次观测值比较：未变化返回 False；变化则自动应用对应主题
        （set_theme 内部会写入 QSettings 的 ui/theme）并返回 True。
        """
        current = self._system_theme_reader()
        if current == self._last_system_theme:
            return False
        self._last_system_theme = current
        if current in TOKENS:
            self.set_theme(current)
        return True

    def start_system_theme_polling(
        self,
        interval_ms: int = SYSTEM_THEME_POLL_INTERVAL_MS,
        parent: QObject | None = None,
    ) -> QTimer:
        """开启系统主题轮询计时器（默认每 5 秒检查一次），重复调用复用。"""
        if self._poll_timer is not None:
            return self._poll_timer
        timer = QTimer(parent if parent is not None else self)
        timer.setInterval(interval_ms)
        timer.timeout.connect(self.check_system_theme_changed)
        timer.start()
        self._poll_timer = timer
        return timer

    def _apply(self) -> None:
        tokens = TOKENS[self._theme]
        self._app.setStyleSheet(build_stylesheet(tokens))
        # PlusMinusSpinBox 从应用属性读取符号颜色，保证双主题下清晰可见。
        self._app.setProperty("ow_spin_symbol_color", tokens.text_dim)
        self._app.setProperty("ow_spin_symbol_hover_color", tokens.text)
        # 自绘按钮方块的底色/边框色（hover 用高亮底）
        self._app.setProperty("ow_spin_btn_bg", tokens.hover)
        self._app.setProperty("ow_spin_btn_bg_hover", tokens.neutral_border_hover)
        self._app.setProperty("ow_spin_btn_border", tokens.neutral_border_hover)
