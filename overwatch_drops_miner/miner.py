from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

from overwatch_drops_miner.account_log_context import (
    clear_current_account,
    set_current_account,
)
from overwatch_drops_miner.client import BilibiliClient
from overwatch_drops_miner.config import MinerConfig
from overwatch_drops_miner.notifier import MultiPlatformNotifier
from overwatch_drops_miner.watch_time_tracker import WatchTimeTracker
from overwatch_drops_miner.x25kn_worker import X25KnWorker

LOGGER = logging.getLogger(__name__)
LOGIN_WATCHDOG_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class SessionPlan:
    room_id: int
    session_no: int


class BilibiliWatchTimeMiner:
    def __init__(
        self,
        config: MinerConfig,
        watch_tracker: WatchTimeTracker | None = None,
        account_id: str = "",
    ) -> None:
        self.config = config
        self.watch_tracker = watch_tracker
        self._account_id = account_id
        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._uid: int | None = None
        self._notifier = MultiPlatformNotifier(config.notify_urls)
        self._clients: list[BilibiliClient] = []
        self._clients_lock = threading.Lock()
        self._force_stop_requested = False
        self._login_invalidated = threading.Event()

    @property
    def uid(self) -> int | None:
        return self._uid

    @property
    def login_invalidated(self) -> bool:
        return self._login_invalidated.is_set()

    def _build_session_plans(self) -> list[SessionPlan]:
        plans: list[SessionPlan] = []
        for room_id in self.config.room_ids:
            for session_no in range(1, self.config.thread_count + 1):
                plans.append(SessionPlan(room_id=room_id, session_no=session_no))
        return plans

    async def _probe_login(self) -> tuple[int | None, str]:
        client = BilibiliClient(self.config.cookie)
        try:
            return await client.get_self_info()
        finally:
            await client.close()

    async def _thread_loop(self, plan: SessionPlan, thread_index: int) -> None:
        # 1s stagger is the bench-verified floor under 128 threads: 0.5s triggers server throttle, 0.75s exhausts local proxy.
        if thread_index > 1 and await asyncio.to_thread(
            self._stop_event.wait, (thread_index - 1) * 1
        ):
            return
        if self._stop_event.is_set():
            return

        client = BilibiliClient(self.config.cookie)
        with self._clients_lock:
            # The Cookie may have changed while this client was being built.
            # Registration and updates share this lock, so calibrate against
            # the latest committed Cookie before publishing the client.
            client.update_cookie(self.config.cookie)
            self._clients.append(client)

        worker: X25KnWorker | None = None
        task: asyncio.Task[None] | None = None
        try:
            if self._uid is None:
                try:
                    uid, _ = await client.get_self_info()
                except Exception as exc:
                    # 首次获取 uid 失败只终结当前连接，不触发全局停机，
                    # 其余房间的连接应继续正常运行。
                    LOGGER.error(
                        "直播间 %s 连接 #%s 获取用户信息失败，本次连接退出: %s",
                        plan.room_id,
                        plan.session_no,
                        exc,
                    )
                    return
                if uid is None:
                    # uid 获取失败时直接退出，避免以 uid=0 启动 worker。
                    LOGGER.error(
                        "直播间 %s 连接 #%s 获取用户信息返回空 UID，本次连接退出",
                        plan.room_id,
                        plan.session_no,
                    )
                    return
                self._uid = uid
            runtime_uid = self._uid or 0

            worker = X25KnWorker(
                client=client,
                notifier=self._notifier,
                config=self.config,
                uid=runtime_uid,
                room_id=plan.room_id,
                session_id=f"s{plan.session_no}",
                primary_session=plan.session_no == 1,
                watch_tracker=self.watch_tracker if plan.session_no == 1 else None,
                account_id=self._account_id,
            )
            task = asyncio.create_task(
                worker.run_forever(),
                name=f"x25kn-{plan.room_id}-s{plan.session_no}",
            )
            LOGGER.info("直播间 %s 连接 #%s 已启动", plan.room_id, plan.session_no)

            while not self._stop_event.is_set():
                if await asyncio.to_thread(self._stop_event.wait, 1):
                    break
        finally:
            if worker is not None:
                try:
                    await worker.stop()
                except Exception:
                    LOGGER.debug(
                        "停止 worker 失败 room=%s session=%s",
                        plan.room_id,
                        plan.session_no,
                        exc_info=True,
                    )

            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

            with self._clients_lock:
                if client in self._clients:
                    self._clients.remove(client)

            try:
                await client.close()
            except Exception:
                LOGGER.debug(
                    "关闭 HTTP client 失败 room=%s session=%s",
                    plan.room_id,
                    plan.session_no,
                    exc_info=True,
                )

    def _thread_entry(self, plan: SessionPlan, thread_index: int) -> None:
        set_current_account(self._account_id)
        try:
            asyncio.run(self._thread_loop(plan, thread_index))
        except Exception:
            # 意外异常只终结当前连接线程，不设置全局停止事件，
            # 其余连接与主循环不受影响；主循环检测到全部线程
            # 退出后会自然收尾。
            LOGGER.exception("直播间连接异常退出")
        finally:
            clear_current_account()

    def run(self) -> None:
        self._stop_event.clear()
        self._force_stop_requested = False
        self._login_invalidated.clear()

        # 启动探测带一次重试并对异常给出明确文案（D-12）：瞬时网络错误
        # 不应被上层 catch-all 降格为 "worker crashed"，让用户无法区分
        # 是网络抖动还是 Cookie 失效。
        uid: int | None = None
        uname = ""
        probe_error: Exception | None = None
        for attempt in range(2):
            try:
                uid, uname = asyncio.run(self._probe_login())
                probe_error = None
                break
            except Exception as exc:
                probe_error = exc
                LOGGER.warning(
                    "启动登录检测失败（第 %s/2 次）：%s", attempt + 1, exc
                )
                if attempt == 0:
                    time.sleep(1.0)
        if probe_error is not None:
            raise RuntimeError(
                f"启动登录检测失败，请检查网络后重试：{probe_error}"
            ) from probe_error
        self._uid = uid
        if uid is None:
            self._login_invalidated.set()
            raise RuntimeError("Cookie 已失效，无法启动")
        LOGGER.info("登录成功: %s (UID: %s)", uname, uid)

        plans = self._build_session_plans()
        LOGGER.info(
            "开始运行: 房间 %s，每房间 %s 个连接",
            self.config.room_ids,
            self.config.thread_count,
        )
        if self.config.task_ids:
            LOGGER.info(
                "任务追踪已开启，每 %s 秒查询一次",
                self.config.task_query_interval_seconds,
            )
        else:
            LOGGER.info("任务追踪未开启（未设置任务 ID）")

        if self._notifier.enabled:
            LOGGER.info("通知推送已开启（%s 个地址）", len(self.config.notify_urls))
        elif self.config.notify_urls:
            LOGGER.warning("通知地址已配置但推送服务不可用")

        self._threads.clear()
        for thread_index, plan in enumerate(plans, start=1):
            thread = threading.Thread(
                target=self._thread_entry,
                args=(plan, thread_index),
                name=f"room-{plan.room_id}-s{plan.session_no}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

        next_login_check = time.monotonic() + LOGIN_WATCHDOG_INTERVAL_SECONDS
        try:
            while not self._stop_event.is_set():
                if not any(thread.is_alive() for thread in self._threads):
                    break
                if time.monotonic() >= next_login_check:
                    try:
                        loop = asyncio.new_event_loop()
                        try:
                            checked_uid, _ = loop.run_until_complete(self._probe_login())
                        finally:
                            loop.close()
                    except Exception as exc:
                        LOGGER.warning("登录状态复检失败，将稍后重试: %s", exc)
                    else:
                        if checked_uid is None:
                            LOGGER.error("Cookie 已失效，正在自动停止")
                            self._login_invalidated.set()
                            self.stop()
                            break
                        if checked_uid != self._uid:
                            LOGGER.error("Cookie 所属账号已变化，正在自动停止")
                            self._login_invalidated.set()
                            self.stop()
                            break
                    next_login_check = (
                        time.monotonic() + LOGIN_WATCHDOG_INTERVAL_SECONDS
                    )
                for thread in self._threads:
                    thread.join(timeout=0.1)
                    # 收到停止请求时立即跳出本轮 join，避免 128 线程全活时
                    # 单轮轮询耗时过长而推迟 stop 响应与登录看门狗复检。
                    if self._stop_event.is_set():
                        break
        finally:
            self.stop(force=self._force_stop_requested)
            join_timeout = 1.2 if self._force_stop_requested else 3.0
            # 收尾等待设总上限（J-5）：极端情况下个别连接线程 hang 死时，
            # 无限等待会让 GUI 永远显示"运行中"；超时后放弃等待并明确告警，
            # daemon 线程随进程退出（GUI 侧 poll 会把会话标记为 stopped）。
            join_deadline = time.monotonic() + (
                8.0 if self._force_stop_requested else 20.0
            )
            gave_up = False
            next_warning_at = time.monotonic() + join_timeout
            while True:
                alive_threads = [
                    thread for thread in self._threads if thread.is_alive()
                ]
                if not alive_threads:
                    break
                if time.monotonic() >= join_deadline:
                    gave_up = True
                    break

                # Keep the miner's owner thread alive until every session has
                # released its client and event loop. The GUI polls this owner
                # thread, so these short joins never block the GUI thread.
                for thread in alive_threads:
                    thread.join(timeout=0.2)

                if time.monotonic() >= next_warning_at:
                    alive_names = [
                        thread.name for thread in alive_threads if thread.is_alive()
                    ]
                    if alive_names:
                        preview = ", ".join(alive_names[:5])
                        if len(alive_names) > 5:
                            preview += f" ... 共 {len(alive_names)} 个"
                        LOGGER.warning("停止未完成，仍有线程未退出: %s", preview)
                    next_warning_at = time.monotonic() + join_timeout

            if gave_up:
                stuck_names = [
                    thread.name for thread in self._threads if thread.is_alive()
                ]
                LOGGER.error(
                    "等待 %s 秒后仍有 %s 个连接线程未退出，放弃等待并继续收尾，"
                    "这些线程将在进程退出时结束: %s",
                    8.0 if self._force_stop_requested else 20.0,
                    len(stuck_names),
                    ", ".join(stuck_names[:5]),
                )

            LOGGER.info("所有连接已停止")

            self._threads.clear()
            with self._clients_lock:
                self._clients.clear()

    def stop(self, *, force: bool = False) -> None:
        # Keep GUI compatibility: force flag is accepted and can tighten join budget.
        if force:
            self._force_stop_requested = True
        self._stop_event.set()

    def update_notifier(self, notify_urls: list[str]) -> None:
        self.config.notify_urls = notify_urls
        self._notifier.update_urls(notify_urls)
