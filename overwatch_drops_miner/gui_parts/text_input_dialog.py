from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from overwatch_drops_miner.gui_parts.styles import make_button


class TextInputDialog(QDialog):
    """主程序风格的文本输入对话框（跟随全局双主题 QSS）。"""

    def __init__(
        self,
        parent: QWidget | None,
        title: str,
        label: str,
        *,
        multiline: bool = False,
        initial_text: str = "",
        placeholder: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)

        caption = QLabel(label)
        caption.setWordWrap(True)
        layout.addWidget(caption)

        if multiline:
            self._editor: QPlainTextEdit | QLineEdit = QPlainTextEdit()
            self._editor.setPlaceholderText(placeholder)
            self._editor.setMinimumHeight(140)
            self._editor.setPlainText(initial_text)
        else:
            self._editor = QLineEdit()
            self._editor.setPlaceholderText(placeholder)
            self._editor.setText(initial_text)
        layout.addWidget(self._editor)

        divider = QFrame()
        divider.setObjectName("hline")
        layout.addWidget(divider)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_button = make_button("保存", "primary", self.accept)
        self.cancel_button = make_button("取消", "neutral", self.reject)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    def text(self) -> str:
        if isinstance(self._editor, QPlainTextEdit):
            return self._editor.toPlainText()
        return self._editor.text()
