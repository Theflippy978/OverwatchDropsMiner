from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from overwatch_drops_miner.gui_parts.account_panel import AccountPanel
from overwatch_drops_miner.gui_parts.plus_minus_spinbox import PlusMinusSpinBox
from overwatch_drops_miner.gui_parts.styles import make_button

MAX_THREAD_COUNT = 128
THREADS_TOOLTIP = "建议线程数60~80，最大128"


@dataclass(slots=True)
class MainWindowCallbacks:
    start: Callable[..., None]
    stop: Callable[..., None]
    load_config: Callable[..., None]
    save_config: Callable[..., None]
    clear_logs: Callable[..., None]
    claim_rewards: Callable[..., None]
    refresh_tasks: Callable[..., None]
    toggle_log: Callable[..., None]
    auto_fetch_room_id: Callable[..., None]
    auto_fetch_task_ids_mode1: Callable[..., None]
    auto_fetch_task_ids_mode2: Callable[..., None]
    toggle_theme: Callable[..., None]


@dataclass(slots=True)
class MainWindowWidgets:
    account_panel: AccountPanel
    running_count_label: QLabel
    theme_button: QPushButton
    rooms_edit: QLineEdit
    task_ids_edit: QLineEdit
    notify_urls_edit: QLineEdit
    threads_spin: PlusMinusSpinBox
    reconnect_spin: PlusMinusSpinBox
    task_interval_spin: PlusMinusSpinBox
    verbose_check: QCheckBox
    disable_task_notify_check: QCheckBox
    progress_bar: QProgressBar
    watch_info_label: QLabel
    task_progress_bar: QProgressBar
    task_text: QPlainTextEdit
    log_text: QPlainTextEdit
    log_card: QFrame
    log_toggle_btn: QPushButton
    claim_rewards_btn: QPushButton
    auto_claim_rewards_check: QCheckBox
    account_status_label: QLabel
    start_btn: QPushButton
    stop_btn: QPushButton
    content_scroll: QScrollArea
    scroll_content: QWidget


def build_main_window_layout(
    window: QMainWindow,
    callbacks: MainWindowCallbacks,
) -> MainWindowWidgets:
    central = QWidget(window)
    window.setCentralWidget(central)
    root_layout = QVBoxLayout(central)
    root_layout.setContentsMargins(14, 12, 14, 12)
    root_layout.setSpacing(10)

    # ---- 顶栏 ----
    header = QHBoxLayout()
    header.setSpacing(12)
    title = QLabel("守望先锋直播掉宝助手")
    title_font = QFont()
    title_font.setPointSize(14)
    title_font.setBold(True)
    title.setFont(title_font)
    header.addWidget(title)
    running_count_label = QLabel("未运行任何账号")
    running_count_label.setObjectName("dimLabel")
    running_count_label.setTextFormat(Qt.PlainText)
    header.addWidget(running_count_label)
    header.addStretch(1)
    theme_button = make_button("切换主题", "purple", callbacks.toggle_theme)
    # J-8：说明系统主题跟随语义——手动选择会持续到系统深浅色再次变化
    theme_button.setToolTip(
        "在深色/浅色主题间切换。\n"
        "注意：Windows 系统深浅色变化时会自动跟随并覆盖手动选择。"
    )
    header.addWidget(theme_button)
    root_layout.addLayout(header)

    # ---- 主体：左账号栏 + 右内容区 ----
    body = QHBoxLayout()
    body.setSpacing(10)

    account_panel = AccountPanel()
    body.addWidget(account_panel)

    content = QVBoxLayout()
    content.setSpacing(10)

    # ---- 共享配置卡 ----
    config_card = _make_card()
    config_layout = QVBoxLayout(config_card)
    config_layout.setContentsMargins(18, 14, 18, 14)
    config_layout.setSpacing(10)

    rooms_edit = _make_line_edit("必填: 直播间号，多个用逗号分隔")
    rooms_edit.setText("23612045")
    task_ids_edit = _make_line_edit("可留空: 可用静态解析或浏览器嗅探自动获取")
    notify_urls_edit = _make_line_edit("可留空: 通知 URL，如 gotify://host/token")

    config_layout.addLayout(
        _build_labeled_row(
            "房间号",
            rooms_edit,
            (("自动获取", "primary", callbacks.auto_fetch_room_id),),
        )
    )
    config_layout.addLayout(
        _build_labeled_row(
            "任务 ID",
            task_ids_edit,
            (
                ("自动获取模式1", "primary", callbacks.auto_fetch_task_ids_mode1),
                ("自动获取模式2", "primary", callbacks.auto_fetch_task_ids_mode2),
            ),
        )
    )
    config_layout.addLayout(_build_labeled_row("通知 URL", notify_urls_edit))

    threads_spin = PlusMinusSpinBox()
    threads_spin.setRange(1, MAX_THREAD_COUNT)
    threads_spin.setValue(1)
    threads_spin.setToolTip(THREADS_TOOLTIP)
    threads_spin.setAlignment(Qt.AlignLeft)
    reconnect_spin = PlusMinusSpinBox()
    reconnect_spin.setRange(1, 3600)   # 秒；上限与 config.validate 对齐（J-12）
    reconnect_spin.setValue(8)
    task_interval_spin = PlusMinusSpinBox()
    task_interval_spin.setRange(1, 3600)
    task_interval_spin.setValue(30)
    verbose_check = QCheckBox("详细日志")
    disable_task_notify_check = QCheckBox("禁用任务完成通知")

    num_row = QHBoxLayout()
    num_row.setSpacing(12)
    threads_label = QLabel("线程数")
    threads_label.setObjectName("dimLabel")
    threads_label.setToolTip(THREADS_TOOLTIP)
    num_row.addWidget(threads_label)
    num_row.addWidget(threads_spin)
    for text, widget in (
        ("重连延迟(s)", reconnect_spin),
        ("任务查询间隔(s)", task_interval_spin),
    ):
        lbl = QLabel(text)
        lbl.setObjectName("dimLabel")
        num_row.addSpacing(6)
        num_row.addWidget(lbl)
        num_row.addWidget(widget)
    num_row.addSpacing(12)
    num_row.addWidget(verbose_check)
    num_row.addWidget(disable_task_notify_check)
    num_row.addStretch(1)
    config_layout.addLayout(num_row)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    start_btn = make_button("启动", "success", callbacks.start)
    stop_btn = make_button("停止", "danger", callbacks.stop)
    btn_row.addWidget(start_btn)
    btn_row.addWidget(stop_btn)
    btn_row.addWidget(make_button("加载配置", "neutral", callbacks.load_config))
    btn_row.addWidget(make_button("保存配置", "neutral", callbacks.save_config))
    btn_row.addStretch(1)
    config_layout.addLayout(btn_row)

    progress_bar = QProgressBar()
    progress_bar.setTextVisible(False)
    progress_bar.setMinimumHeight(6)
    progress_bar.setMaximumHeight(10)
    progress_bar.setRange(0, 1)
    progress_bar.setValue(0)
    progress_bar.setVisible(False)
    config_layout.addWidget(progress_bar)

    content.addWidget(config_card)

    # ---- 挂宝进度卡（当前选中账号）----
    task_card = _make_card()
    task_layout = QVBoxLayout(task_card)
    task_layout.setContentsMargins(18, 12, 18, 14)
    task_layout.setSpacing(8)

    task_header = QHBoxLayout()
    task_header.setSpacing(10)
    task_title = QLabel("挂宝进度")
    task_title_font = QFont()
    task_title_font.setPointSize(11)
    task_title_font.setBold(True)
    task_title.setFont(task_title_font)
    task_header.addWidget(task_title)
    account_status_label = QLabel("未选择账号")
    account_status_label.setObjectName("dimLabel")
    account_status_label.setTextFormat(Qt.PlainText)
    task_header.addWidget(account_status_label)
    task_header.addStretch(1)
    auto_claim_rewards_check = QCheckBox("自动领取")
    auto_claim_rewards_check.setToolTip(
        "检测到任务达到 100% 后自动领取；领取失败会在后续刷新时重试"
    )
    task_header.addWidget(auto_claim_rewards_check)
    claim_rewards_btn = make_button("领取奖励", "primary", callbacks.claim_rewards)
    task_header.addWidget(claim_rewards_btn)
    task_header.addWidget(make_button("手动刷新", "neutral", callbacks.refresh_tasks))
    task_layout.addLayout(task_header)

    watch_info_label = QLabel("状态: 待机 | 本次有效观看: -- | 预计剩余: --")
    watch_info_label.setObjectName("dimLabel")
    watch_info_label.setTextFormat(Qt.PlainText)
    task_layout.addWidget(watch_info_label)

    task_progress_bar = QProgressBar()
    task_progress_bar.setObjectName("taskProgress")
    task_progress_bar.setTextVisible(True)
    task_progress_bar.setFormat("掉宝进度 %p%")
    task_progress_bar.setRange(0, 100)
    task_progress_bar.setValue(0)
    task_layout.addWidget(task_progress_bar)

    task_text = QPlainTextEdit()
    task_text.setReadOnly(True)
    fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    fixed_font.setFamily("Consolas")
    fixed_font.setPointSize(10)
    task_text.setFont(fixed_font)
    task_text.setLineWrapMode(QPlainTextEdit.NoWrap)
    task_text.setMinimumHeight(140)
    task_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    task_text.setPlainText("点击“手动刷新”查看任务进度")
    task_layout.addWidget(task_text, 1)

    content.addWidget(task_card, 1)

    # ---- 日志卡（折叠）----
    log_card = _make_card()
    log_layout = QVBoxLayout(log_card)
    log_layout.setContentsMargins(18, 8, 18, 14)
    log_layout.setSpacing(6)

    log_toggle_btn = QPushButton("▶ 运行日志")
    log_toggle_font = QFont()
    log_toggle_font.setPointSize(11)
    log_toggle_font.setBold(True)
    log_toggle_btn.setFont(log_toggle_font)
    log_toggle_btn.setFlat(True)
    log_toggle_btn.setCursor(Qt.PointingHandCursor)
    log_toggle_btn.setProperty("accent", "ghost")
    log_toggle_btn.clicked.connect(callbacks.toggle_log)
    log_layout.addWidget(log_toggle_btn, 0, Qt.AlignLeft)

    log_text = QPlainTextEdit()
    log_text.setReadOnly(True)
    log_text.setFont(fixed_font)
    log_text.setMaximumBlockCount(5000)
    log_text.setMinimumHeight(140)
    log_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    log_text.setVisible(False)
    log_layout.addWidget(log_text)

    clear_row = QHBoxLayout()
    clear_row.addStretch(1)
    clear_row.addWidget(make_button("清空日志", "neutral", callbacks.clear_logs))
    log_layout.addLayout(clear_row)

    content.addWidget(log_card)

    # 内容区包进滚动容器：仅当日志展开等内容超过窗口高度时才出现滚动条。
    # 收起日志状态下，窗口最小尺寸取自内容最小需求（见下方 setMinimumSize），
    # 保证常规使用时滚动条不会出现。
    scroll_content = QWidget()
    scroll_content.setLayout(content)
    content_scroll = QScrollArea()
    content_scroll.setWidgetResizable(True)
    content_scroll.setFrameShape(QFrame.NoFrame)
    content_scroll.setWidget(scroll_content)
    # 滚动容器的最小宽度 = 内容最小宽度 + 一条垂直滚动条的宽度：
    # 展开日志出现垂直滚动条时正好占用预留宽度，viewport 宽度不变，
    # 内容布局不被挤压，水平方向永远不会需要滚动。
    # 收起时滚动条不出现，多出的预留宽度由弹性控件（输入框等）吸收。
    scrollbar_extent = content_scroll.style().pixelMetric(
        QStyle.PM_ScrollBarExtent, None, content_scroll
    )
    content_min_hint = scroll_content.minimumSizeHint()
    content_scroll.setMinimumSize(
        content_min_hint.width() + scrollbar_extent,
        content_min_hint.height(),
    )
    # 双保险：内容宽度已由最小尺寸保证，禁用水平滚动条杜绝左右翻页。
    content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    body.addWidget(content_scroll, 1)

    root_layout.addLayout(body, 1)

    return MainWindowWidgets(
        account_panel=account_panel,
        running_count_label=running_count_label,
        theme_button=theme_button,
        rooms_edit=rooms_edit,
        task_ids_edit=task_ids_edit,
        notify_urls_edit=notify_urls_edit,
        threads_spin=threads_spin,
        reconnect_spin=reconnect_spin,
        task_interval_spin=task_interval_spin,
        verbose_check=verbose_check,
        disable_task_notify_check=disable_task_notify_check,
        progress_bar=progress_bar,
        watch_info_label=watch_info_label,
        task_progress_bar=task_progress_bar,
        task_text=task_text,
        log_text=log_text,
        log_card=log_card,
        log_toggle_btn=log_toggle_btn,
        claim_rewards_btn=claim_rewards_btn,
        auto_claim_rewards_check=auto_claim_rewards_check,
        account_status_label=account_status_label,
        start_btn=start_btn,
        stop_btn=stop_btn,
        content_scroll=content_scroll,
        scroll_content=scroll_content,
    )


def apply_start_stop_button_state(
    start_btn: QPushButton,
    stop_btn: QPushButton,
    *,
    has_selection: bool,
    running: bool,
) -> None:
    """按账号选中与运行状态联动启停按钮：互斥启用，未选账号则全部禁用。"""
    if not has_selection:
        start_btn.setEnabled(False)
        stop_btn.setEnabled(False)
        return
    start_btn.setEnabled(not running)
    stop_btn.setEnabled(running)


def _make_card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _make_line_edit(placeholder: str) -> QLineEdit:
    widget = QLineEdit()
    widget.setPlaceholderText(placeholder)
    return widget


def _build_labeled_row(
    label: str,
    editor: QLineEdit,
    extra_buttons: tuple[tuple[str, str, Callable[..., None]], ...] = (),
) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    lab = QLabel(label)
    lab.setMinimumWidth(72)
    lab.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    lab.setObjectName("dimLabel")
    row.addWidget(lab)
    editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    row.addWidget(editor, 1)
    for text, accent, slot in extra_buttons:
        button = make_button(text, accent, slot)
        button.setMinimumWidth(90)
        row.addWidget(button)
    return row
