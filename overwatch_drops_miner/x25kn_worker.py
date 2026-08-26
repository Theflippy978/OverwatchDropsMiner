from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from overwatch_drops_miner.account_log_context import (
    clear_current_account,
    set_current_account,
)
from overwatch_drops_miner.client import (
    BilibiliClient,
    LiveTraceSession,
    TaskProgress,
)
from overwatch_drops_miner.client_parts.http import sanitize_exception_text
from overwatch_drops_miner.config import MinerConfig
from overwatch_drops_miner.notifier import MultiPlatformNotifier
from overwatch_drops_miner.watch_time_tracker import WatchTimeTracker

LOGGER = logging.getLogger(__name__)


class X25KnWorker:
    def __init__(
        self,
        client: BilibiliClient,
        notifier: MultiPlatformNotifier,
        config: MinerConfig,
        uid: int,
        room_id: int,
        session_id: str = "",
        primary_session: bool = True,
        stop_event: asyncio.Event | None = None,
        watch_tracker: WatchTimeTracker | None = None,
        account_id: str = "",
    ) -> None:
        self.client = client
        self.notifier = notifier
        self.config = config
        self.uid = uid
        self.room_id = room_id
        self.session_id = session_id
        self.primary_session = primary_session
        self._stop_event = stop_event or asyncio.Event()
        self.watch_tracker = watch_tracker
        self.account_id = account_id
        # 跨重连保留的任务进度快照与已完成去重集合：
        # 断线重连会重新进入 _run_once 并新建监控循环，
        # 若放在局部变量会导致重连后重复推送“任务完成”通知、重复打印全部进度。
        # 监控循环在同一事件循环内顺序执行，无并发访问，直接提升为实例字段即可。
        self._last_task_snapshot: dict[
            str, tuple[int | float, int | float, int]
        ] = {}
        self._notified_completed_ids: set[str] = set()

    @property
    def _ctx(self) -> str:
        if self.session_id:
            return f"room={self.room_id} session={self.session_id}"
        return f"room={self.room_id}"

    def _log_info(self, message: str, *args: Any, primary_only: bool = False) -> None:
        if primary_only and not self.primary_session:
            LOGGER.debug(message, *args)
            return
        LOGGER.info(message, *args)

    def _log_warning(
        self, message: str, *args: Any, primary_only: bool = False
    ) -> None:
        if primary_only and not self.primary_session:
            LOGGER.debug(message, *args)
            return
        LOGGER.warning(message, *args)

    async def stop(self) -> None:
        self._stop_event.set()
        if self.watch_tracker is not None:
            self.watch_tracker.pause()

    async def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log_warning(
                    "直播间 %s x25Kn 运行异常: %s",
                    self.room_id,
                    exc,
                    primary_only=True,
                )
            if not self._stop_event.is_set():
                # 等待期间响应停止请求，避免停止动作最多延迟一个重连间隔
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.config.reconnect_delay_seconds,
                    )
                except asyncio.TimeoutError:
                    pass

    async def _run_once(self) -> None:
        trace_heartbeat_task = asyncio.create_task(self._trace_heartbeat_loop())
        task_monitor_task = (
            asyncio.create_task(self._task_monitor_loop()) if self.primary_session else None
        )
        stop_wait_task = asyncio.create_task(self._stop_event.wait())

        tasks: list[asyncio.Task[Any]] = [trace_heartbeat_task, stop_wait_task]
        if task_monitor_task is not None:
            tasks.append(task_monitor_task)

        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if stop_wait_task in done:
                return

            exceptions: list[BaseException] = []
            for task in done:
                if task is stop_wait_task:
                    continue
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    # 记录全部子任务异常，避免只 raise 第一个时丢失其余根因
                    LOGGER.error(
                        "%s 子任务异常退出: %s", self._ctx, exc, exc_info=exc
                    )
                    exceptions.append(exc)

            if exceptions:
                raise exceptions[0]

            raise RuntimeError("x25Kn 子任务意外退出")

        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _trace_heartbeat_loop(self) -> None:
        session: LiveTraceSession | None = None
        wait_seconds = 60
        while not self._stop_event.is_set():
            try:
                if session is None:
                    await self.client.room_entry_action(self.room_id)
                    session = await self.client.live_trace_enter(self.room_id)
                    wait_seconds = max(5, int(session.heartbeat_interval))
                    if self.watch_tracker is not None:
                        self.watch_tracker.resume()
                    self._log_info(
                        "直播间 %s 观看时长上报已启动",
                        self.room_id,
                        primary_only=True,
                    )
                else:
                    session = await self.client.live_trace_heartbeat(session)
                    wait_seconds = max(5, int(session.heartbeat_interval))
                    if self.watch_tracker is not None:
                        # resume 幂等：多房间共享同一 tracker 时，任一房间的
                        # 一次失败会 pause 时钟，健康房间心跳成功即恢复，
                        # 避免本地观看估算被无关房间长期冻结（Z-3）。
                        self.watch_tracker.resume()
                    LOGGER.debug(
                        "%s x25Kn heartbeat success seq=%s ets=%s interval=%s",
                        self._ctx,
                        session.seq_id,
                        session.ets,
                        wait_seconds,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # httpx 异常消息携带完整 URL（含 csrf 等敏感参数），脱敏后入日志
                detail = sanitize_exception_text(exc).strip() or repr(exc)
                if self.watch_tracker is not None:
                    self.watch_tracker.pause()
                self._log_warning(
                    "直播间 %s 观看时长上报失败[%s]: %s",
                    self.room_id,
                    type(exc).__name__,
                    detail,
                    primary_only=True,
                )
                session = None
                wait_seconds = max(5, self.config.reconnect_delay_seconds)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                return
            except asyncio.TimeoutError:
                pass

    async def _task_monitor_loop(self) -> None:
        # 使用实例级快照与去重集合，保证跨断线重连不重复通知（首次见到已完成任务仍会通知）
        last_snapshot = self._last_task_snapshot
        notified_completed_ids = self._notified_completed_ids
        while not self._stop_event.is_set():
            task_ids = self.config.task_ids
            wait_seconds = max(10, self.config.task_query_interval_seconds)
            if not task_ids:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=wait_seconds
                    )
                    return
                except asyncio.TimeoutError:
                    continue
            try:
                progresses = await self.client.get_task_progress(task_ids)
                if not progresses:
                    LOGGER.warning("未获取到任务进度，请检查任务 ID 是否正确")
                else:
                    for task in progresses:
                        key = task.task_id
                        current = (task.cur_value, task.limit_value, task.status)
                        previous = last_snapshot.get(key)
                        # 周期任务（日/周）重置后 cur 归零、status 复位：
                        # 检测「上一帧完成、当前未完成」的迁移并清出去重
                        # 集合，让第二个周期完成时能再次推送通知（Z-4）。
                        if (
                            previous is not None
                            and key in notified_completed_ids
                            and task.is_completed is False
                        ):
                            notified_completed_ids.discard(key)
                        if previous != current:
                            self._log_info(
                                "任务进度: %s %s/%s",
                                task.task_name,
                                task.cur_value,
                                task.limit_value,
                                primary_only=True,
                            )
                            last_snapshot[key] = current
                        if (
                            self.config.notify_on_task_complete
                            and task.is_completed
                            and key not in notified_completed_ids
                        ):
                            notified_completed_ids.add(key)
                            self._log_info(
                                "任务完成: %s (%s/%s)",
                                task.task_name,
                                task.cur_value,
                                task.limit_value,
                                primary_only=True,
                            )
                            self._dispatch_task_complete_notification(task)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.debug("查询任务进度失败: %s", exc)
                wait_seconds = max(10, self.config.reconnect_delay_seconds)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
                return
            except asyncio.TimeoutError:
                pass

    def _send_task_complete_notification(self, task: TaskProgress) -> None:
        if not self.notifier.enabled:
            return
        title = "直播掉宝任务完成"
        body = (
            f"直播间: {self.room_id}\n"
            f"任务: {task.task_name}\n"
            f"进度: {task.cur_value}/{task.limit_value}"
        )
        sent = self.notifier.notify(title=title, body=body)
        if sent:
            self._log_info(
                "已发送通知: %s",
                task.task_name,
                primary_only=True,
            )

    def _dispatch_task_complete_notification(self, task: TaskProgress) -> None:
        # Notification adapters are synchronous and may wait on network
        # timeouts. A daemon thread keeps them outside the session event loop;
        # unlike asyncio's default executor, it also cannot delay loop shutdown.
        def deliver() -> None:
            set_current_account(self.account_id)
            try:
                self._send_task_complete_notification(task)
            finally:
                clear_current_account()

        threading.Thread(
            target=deliver,
            args=(),
            name=f"notify-{self.room_id}-{task.task_id}",
            daemon=True,
        ).start()
