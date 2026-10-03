from __future__ import annotations

import logging
import threading
from typing import Callable

from python_sidecar.backend.accounts import Account
from python_sidecar.backend.config import MinerConfig
from python_sidecar.backend.browser.worker_controller import WorkerController
from python_sidecar.backend.watch_time_tracker import WatchTimeTracker

LOGGER = logging.getLogger(__name__)

ConfigBuilder = Callable[[str], MinerConfig]
StateListener = Callable[[str, bool], None]


class AccountMinerManager:
    """Runs one miner per account against a shared GUI configuration."""

    def __init__(self, config_builder: ConfigBuilder) -> None:
        self._config_builder = config_builder
        self._lock = threading.Lock()
        self._sessions: dict[str, _AccountSession] = {}
        self._listeners: list[StateListener] = []

    def add_state_listener(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    def _notify(self, account_id: str, running: bool) -> None:
        for listener in self._listeners:
            try:
                listener(account_id, running)
            except Exception:
                LOGGER.exception("账号状态监听器异常")

    def is_running(self, account_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(account_id)
        return session is not None and session.controller.is_running

    def running_count(self) -> int:
        with self._lock:
            return sum(
                1
                for session in self._sessions.values()
                if session.controller.is_running
            )

    def tracker(self, account_id: str) -> WatchTimeTracker | None:
        with self._lock:
            session = self._sessions.get(account_id)
        return session.tracker if session else None

    def is_login_invalidated(self, account_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(account_id)
            if session and session.controller.miner:
                return session.controller.miner.login_invalidated
        return False

    def start(self, account: Account, *, logger: logging.Logger | None = None) -> bool:
        log = logger or LOGGER
        cookie = account.cookie()
        if not cookie.strip():
            log.warning("账号 %s Cookie 为空，无法启动", account.remark or account.id)
            return False
        with self._lock:
            session = self._sessions.get(account.id)
            if session is not None and session.controller.is_running:
                return False
            if session is None:
                session = _AccountSession(
                    controller=WorkerController(),
                    tracker=WatchTimeTracker(),
                )
                self._sessions[account.id] = session

        config = self._config_builder(cookie)
        config.cookie = cookie
        session.tracker.reset()
        started = session.controller.start(
            config,
            logger=logging.getLogger(
                f"overwatch_miner.account.{account.id[:8]}"
            ),
            account_id=account.id,
            watch_tracker=session.tracker,
        )
        if started:
            log.info(
                "账号 [%s] 挂宝已启动（房间 %s，线程 %s）",
                account.remark or account.id[:8],
                config.room_ids,
                config.thread_count,
            )
            self._notify(account.id, True)
        return started

    def request_stop(self, account_id: str, *, logger: logging.Logger | None = None) -> str:
        log = logger or LOGGER
        with self._lock:
            session = self._sessions.get(account_id)
        if session is None:
            return "not_running"
        result = session.controller.request_stop(logger=log)
        if result in ("stopping_started", "not_running"):
            self._notify(account_id, False)
        return result

    def poll_shutdown(self, account_id: str, *, logger: logging.Logger | None = None) -> str:
        with self._lock:
            session = self._sessions.get(account_id)
        if session is None:
            return "no_thread"
        result = session.controller.poll_shutdown(
            logger=logger or LOGGER
        )
        if result == "stopped":
            if session.tracker is not None:
                session.tracker.pause()
            self._notify(account_id, False)
        return result

    def discard_session(self, account_id: str) -> None:
        """回收已删除账号的会话资源（J-6）：_sessions 此前只增不减，
        删除账号后 controller/tracker 常驻内存。仅在会话完全停止时移除。"""
        with self._lock:
            session = self._sessions.get(account_id)
            if session is None:
                return
            if session.controller.is_running or session.controller.has_thread:
                # 尚未完全停止（线程还在退出收尾），等下次轮询再回收
                return
            del self._sessions[account_id]

    def running_miners(self) -> list:
        from python_sidecar.backend.miner import BilibiliWatchTimeMiner

        with self._lock:
            miners: list[BilibiliWatchTimeMiner] = []
            for session in self._sessions.values():
                if session.controller.is_running and session.controller.miner:
                    miners.append(session.controller.miner)
            return miners

    def stop_all(self, *, force: bool = False) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            miner = session.controller.miner
            if miner is None:
                continue
            try:
                miner.stop(force=force)
            except Exception:
                LOGGER.exception("停止账号会话失败")

    def shutdown_states(self) -> dict[str, str]:
        with self._lock:
            items = list(self._sessions.items())
        return {
            account_id: (
                "running" if session.controller.is_running else "idle"
            )
            for account_id, session in items
        }


class _AccountSession:
    __slots__ = ("controller", "tracker")

    def __init__(
        self, controller: WorkerController, tracker: WatchTimeTracker
    ) -> None:
        self.controller = controller
        self.tracker = tracker
