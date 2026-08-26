from __future__ import annotations

import logging
import os
import sys

try:
    from colorama import just_fix_windows_console
except Exception:  # pragma: no cover
    def just_fix_windows_console() -> None:
        return None


# 项目内所有模块 logger 均为 getLogger(__name__)，即以本包名为根的层次；
# verbose 开关必须设在这个名字上才能覆盖全部模块（历史上误写成
# "overwatch_miner" 导致「详细日志」完全失效）。
PACKAGE_LOGGER_NAME = "overwatch_drops_miner"

RESET = "\x1b[0m"
LEVEL_COLORS = {
    logging.DEBUG: "\x1b[36m",
    logging.INFO: "\x1b[32m",
    logging.WARNING: "\x1b[33m",
    logging.ERROR: "\x1b[31m",
    logging.CRITICAL: "\x1b[35m",
}
LEVEL_LABEL = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO ",
    logging.WARNING: "WARN ",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "FATAL",
}


class PrettyFormatter(logging.Formatter):
    def __init__(self, *, verbose: bool, use_color: bool) -> None:
        if verbose:
            fmt = "%(asctime)s | %(levelname)s | %(threadName)-18s | %(name)s:%(lineno)d | %(message)s"
        else:
            fmt = "%(asctime)s | %(message)s"
        super().__init__(fmt=fmt, datefmt="%H:%M:%S")
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        label = LEVEL_LABEL.get(record.levelno, record.levelname[:5].upper())
        if self.use_color:
            label = f"{LEVEL_COLORS.get(record.levelno, '')}{label}{RESET}"
        # 在副本上替换 levelname，避免多 handler 并发时篡改公共 record 造成串色竞态
        replica = logging.makeLogRecord(record.__dict__.copy())
        replica.levelname = label
        return super().format(replica)


def setup_logging(
    *,
    verbose: bool,
    no_color: bool = False,
    extra_handlers: list[logging.Handler] | None = None,
) -> None:
    just_fix_windows_console()
    # StreamHandler 默认绑定 stderr，颜色判定应以实际输出流为准
    use_color = (
        not no_color
        and not bool(os.environ.get("NO_COLOR"))
        and getattr(sys.stderr, "isatty", lambda: False)()
    )

    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    root_logger.setLevel(logging.INFO)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG)
    formatter = PrettyFormatter(verbose=verbose, use_color=use_color)
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)

    for handler in extra_handlers or []:
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    app_level = logging.DEBUG if verbose else logging.INFO
    logging.getLogger(PACKAGE_LOGGER_NAME).setLevel(app_level)
    for logger_name in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def apply_verbose_runtime(*, verbose: bool, no_color: bool = True) -> None:
    """不重建任何 handler 的轻量 verbose 切换（热路径复用）。

    setup_logging 每次都会移除并 close 根 logger 全部 handler 再重建，
    在已有 worker 线程持续打日志时存在「零 handler 窗口」与对已关闭
    handler 并发 emit 的风险；重复调用场景（如每次启动账号）应改用本
    函数：仅同步包级 logger 有效级别并替换各 handler 的格式器。
    """
    apply_verbose_level(verbose=verbose)
    formatter = PrettyFormatter(verbose=verbose, use_color=not no_color)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def apply_verbose_level(*, verbose: bool) -> None:
    """仅同步包级 logger 有效级别，不触碰 handler。"""
    app_level = logging.DEBUG if verbose else logging.INFO
    logging.getLogger(PACKAGE_LOGGER_NAME).setLevel(app_level)
