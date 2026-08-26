from __future__ import annotations

import logging
import threading
import time
from typing import Literal

from overwatch_drops_miner.config import MinerConfig
from overwatch_drops_miner.miner import BilibiliWatchTimeMiner
from overwatch_drops_miner.watch_time_tracker import WatchTimeTracker

StopRequestResult = Literal[
    "not_running",
    "stopping_started",
    "force_requested",
    "already_stopping",
]
PollResult = Literal["no_thread", "running", "stopped"]


class WorkerController:
    def __init__(self, *, auto_force_stop_after_seconds: float = 2.0) -> None:
        # start 全程持锁（J-1）：虽然当前所有调用都来自 GUI 单线程事件循环，
        # 锁可以让"检查-创建-启动"序列对未来的跨线程调用保持原子。
        self._start_lock = threading.Lock()
        self.worker_thread: threading.Thread | None = None
        self.miner: BilibiliWatchTimeMiner | None = None
        self.stopping_in_progress = False
        self.stop_poll_started_at: float | None = None
        self.stop_timeout_warned = False
        self.stop_force_sent = False
        self.auto_force_stop_after_seconds = auto_force_stop_after_seconds

    @property
    def is_running(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.is_alive()

    @property
    def has_thread(self) -> bool:
        return self.worker_thread is not None

    def start(
        self,
        config: MinerConfig,
        *,
        logger: logging.Logger,
        account_id: str = "",
        watch_tracker: WatchTimeTracker | None = None,
    ) -> bool:
        with self._start_lock:
            # A completed worker remains owned until the GUI poll finalizes it.
            # Do not replace its miner reference in that small window.
            if self.has_thread:
                return False

            self._reset_stop_state()

            miner = BilibiliWatchTimeMiner(
                config, watch_tracker=watch_tracker, account_id=account_id
            )
            self.miner = miner

            def runner() -> None:
                try:
                    miner.run()
                except Exception:
                    logger.exception("GUI worker crashed")

            thread = threading.Thread(
                target=runner, name="gui-main-worker", daemon=True
            )
            self.worker_thread = thread
            thread.start()
            return True

    def request_stop(self, *, logger: logging.Logger) -> StopRequestResult:
        if not self.is_running:
            self.worker_thread = None
            self.miner = None
            self._reset_stop_state()
            return "not_running"

        if self.stopping_in_progress:
            if self.miner is not None and not self.stop_force_sent:
                self.stop_force_sent = True
                self.miner.stop(force=True)
                logger.warning("停止较慢，已请求加速收尾（线程仍需协作式退出）")
                return "force_requested"
            logger.info("正在停止，请稍候...")
            return "already_stopping"

        self.stopping_in_progress = True
        self.stop_poll_started_at = time.monotonic()
        self.stop_timeout_warned = False
        self.stop_force_sent = False
        if self.miner is not None:
            self.miner.stop(force=False)
        logger.info("正在停止...")
        return "stopping_started"

    def poll_shutdown(self, *, logger: logging.Logger) -> PollResult:
        if self.worker_thread is None:
            self.miner = None
            self._reset_stop_state()
            return "no_thread"

        if self.worker_thread.is_alive():
            if not self.stopping_in_progress:
                # 未发出停止请求：正常运行，绝不计时、绝不强停
                return "running"
            if self.stop_poll_started_at is None:
                self.stop_poll_started_at = time.monotonic()
            elapsed = time.monotonic() - self.stop_poll_started_at
            if (
                elapsed >= self.auto_force_stop_after_seconds
                and not self.stop_force_sent
                and self.miner is not None
            ):
                self.stop_force_sent = True
                self.miner.stop(force=True)
                logger.warning(
                    "停止超过 %.1f 秒，已发送加速收尾请求（等待线程自行退出）",
                    self.auto_force_stop_after_seconds,
                )
            if elapsed >= 5 and not self.stop_timeout_warned:
                logger.warning("停止超过 5 秒，后台线程仍在退出中")
                self.stop_timeout_warned = True
            return "running"

        # 线程已死：无论是否请求过停止都做最终清理（支撑崩溃残留自动回收）
        if self.stopping_in_progress:
            logger.info("停止成功")
        else:
            logger.info("后台线程已退出，资源已清理")
        self.worker_thread = None
        self.miner = None
        self._reset_stop_state()
        return "stopped"

    def _reset_stop_state(self) -> None:
        self.stopping_in_progress = False
        self.stop_poll_started_at = None
        self.stop_timeout_warned = False
        self.stop_force_sent = False
