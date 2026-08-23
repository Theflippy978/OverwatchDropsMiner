from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QSizePolicy


# 语义色标（与 theme.py 中 QSS 的 QPushButton[accent=...] 选择器对应）：
# 同一功能在全应用使用同一颜色。
#   primary  - 扫码登录 / 自动获取 / 领取奖励 / 添加账号
#   success  - 启动
#   danger   - 停止 / 删除账号
#   purple   - 浏览器自动捕获类操作
#   neutral  - 次要操作（加载/保存配置、手动刷新、切换主题）
#   ghost    - 折叠/展开等轻量操作


def make_button(
    text: str,
    accent: str,
    slot: Callable[..., None],
    *,
    tooltip: str = "",
) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("accent", accent or "neutral")
    button.setCursor(Qt.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    if tooltip:
        button.setToolTip(tooltip)
    button.clicked.connect(slot)
    return button
