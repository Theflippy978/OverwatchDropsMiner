from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import unittest
from unittest import mock

from python_sidecar.backend.client_parts.models import LiveTraceSession, TaskProgress
from python_sidecar.backend.config import MinerConfig
from python_sidecar.backend.x25kn_worker import X25KnWorker


class _TaskClient:
    def __init__(self) -> None:
        self.query_calls = 0

    async def get_task_progress(self, _task_ids: list[str]) -> list[TaskProgress]:
        self.query_calls += 1
        return [
            TaskProgress(
                task_id="done",
                task_name="观看直播",
                status=3,
                cur_value=1,
                limit_value=1,
            )
        ]


class _HeartbeatClient:
    def __init__(self) -> None:
        self.entry_calls = 0
        self.enter_calls = 0

    async def room_entry_action(self, _room_id: int) -> None:
        self.entry_calls += 1

    async def live_trace_enter(self, room_id: int) -> LiveTraceSession:
        self.enter_calls += 1
        return LiveTraceSession(
            room_id=room_id,
            ruid=1,
            parent_area_id=1,
            area_id=1,
            seq_id=1,
            ets=1,
            heartbeat_interval=60,
            secret_key="secret",
            secret_rule=[],
        )


class _BlockingNotifier:
    enabled = True

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def notify(self, *, title: str, body: str) -> bool:
        try:
            self.started.set()
            self.release.wait(timeout=1)
            return True
        finally:
            self.finished.set()


class _RecordingNotifier:
    enabled = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.notified = threading.Event()

    def notify(self, *, title: str, body: str) -> bool:
        self.calls.append((title, body))
        self.notified.set()
        return True


class X25KnWorkerTest(unittest.TestCase):
    def test_trace_heartbeat_always_starts(self) -> None:
        client = _HeartbeatClient()
        worker = X25KnWorker(
            client=client,  # type: ignore[arg-type]
            notifier=_BlockingNotifier(),  # type: ignore[arg-type]
            config=MinerConfig(cookie="cookie", room_ids=[1]),
            uid=42,
            room_id=1,
        )

        async def exercise() -> None:
            heartbeat = asyncio.create_task(worker._trace_heartbeat_loop())
            for _ in range(20):
                if client.enter_calls:
                    break
                await asyncio.sleep(0)
            await worker.stop()
            await asyncio.wait_for(heartbeat, timeout=0.2)

        asyncio.run(exercise())

        self.assertEqual(client.entry_calls, 1)
        self.assertEqual(client.enter_calls, 1)

    def test_blocking_notification_does_not_delay_event_loop_stop(self) -> None:
        notifier = _BlockingNotifier()
        worker = X25KnWorker(
            client=_TaskClient(),  # type: ignore[arg-type]
            notifier=notifier,  # type: ignore[arg-type]
            config=MinerConfig(
                cookie="cookie",
                room_ids=[1],
                task_ids=["done"],
                task_query_interval_seconds=10,
            ),
            uid=42,
            room_id=1,
        )

        async def exercise() -> None:
            monitor = asyncio.create_task(worker._task_monitor_loop())
            self.assertTrue(
                await asyncio.to_thread(notifier.started.wait, 1),
                "notification did not start",
            )
            await worker.stop()
            await asyncio.wait_for(monitor, timeout=0.2)

        started_at = time.monotonic()
        try:
            asyncio.run(exercise())
            elapsed = time.monotonic() - started_at
            self.assertLess(
                elapsed,
                0.5,
                "asyncio.run waited for the blocking notification thread",
            )
        finally:
            notifier.release.set()
            self.assertTrue(
                notifier.finished.wait(timeout=1),
                "notification thread did not finish after release",
            )

    def test_completed_notify_not_repeated_after_reconnect(self) -> None:
        client = _TaskClient()
        notifier = _RecordingNotifier()
        worker = X25KnWorker(
            client=client,  # type: ignore[arg-type]
            notifier=notifier,  # type: ignore[arg-type]
            config=MinerConfig(
                cookie="cookie",
                room_ids=[1],
                task_ids=["done"],
                task_query_interval_seconds=10,
            ),
            uid=42,
            room_id=1,
        )

        async def exercise() -> None:
            # 第一轮监控循环：见到任务完成并发送通知
            monitor = asyncio.create_task(worker._task_monitor_loop())
            self.assertTrue(
                await asyncio.to_thread(notifier.notified.wait, 1),
                "first round did not notify",
            )
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor

            # 模拟断线重连：同一 worker 重新进入任务监控循环
            monitor2 = asyncio.create_task(worker._task_monitor_loop())
            for _ in range(200):
                if client.query_calls >= 2:
                    break
                await asyncio.sleep(0.01)
            # 留出处理时间，确保第二轮已完成一次完整查询与判定
            await asyncio.sleep(0.05)
            monitor2.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor2

        asyncio.run(exercise())

        self.assertGreaterEqual(client.query_calls, 2)
        self.assertEqual(len(notifier.calls), 1)


    def test_reconnect_wait_respects_stop_event(self) -> None:
        worker = X25KnWorker(
            client=_TaskClient(),  # type: ignore[arg-type]
            notifier=_RecordingNotifier(),  # type: ignore[arg-type]
            config=MinerConfig(
                cookie="cookie",
                room_ids=[1],
                reconnect_delay_seconds=30,
            ),
            uid=42,
            room_id=1,
        )

        async def failing_run_once() -> None:
            raise RuntimeError("boom")

        async def stop_later() -> None:
            await asyncio.sleep(0.05)
            await worker.stop()

        async def exercise() -> float:
            started = time.monotonic()
            with mock.patch.object(worker, "_run_once", failing_run_once):
                await asyncio.wait_for(
                    asyncio.gather(worker.run_forever(), stop_later()),
                    timeout=2,
                )
            return time.monotonic() - started

        elapsed = asyncio.run(exercise())
        # 重连等待必须响应停止请求，不能睡满 30 秒的重连间隔
        self.assertLess(elapsed, 5.0)

    def test_run_once_collects_all_subtask_exceptions(self) -> None:
        worker = X25KnWorker(
            client=_TaskClient(),  # type: ignore[arg-type]
            notifier=_RecordingNotifier(),  # type: ignore[arg-type]
            config=MinerConfig(cookie="cookie", room_ids=[1]),
            uid=42,
            room_id=1,
        )

        async def heartbeat_boom() -> None:
            raise RuntimeError("heartbeat-error")

        async def monitor_boom() -> None:
            raise RuntimeError("monitor-error")

        async def exercise() -> tuple[str, list[str]]:
            with (
                mock.patch.object(worker, "_trace_heartbeat_loop", heartbeat_boom),
                mock.patch.object(worker, "_task_monitor_loop", monitor_boom),
                self.assertLogs(
                    "python_sidecar.backend.x25kn_worker", level="ERROR"
                ) as logs,
                self.assertRaises(RuntimeError) as ctx,
            ):
                await worker._run_once()
            return str(ctx.exception), [r.getMessage() for r in logs.records]

        first_error, logged = asyncio.run(exercise())
        # raise 的具体是哪一个取决于 asyncio.wait 返回集合的迭代顺序，二者皆可
        self.assertIn(first_error, {"heartbeat-error", "monitor-error"})
        joined = "\n".join(logged)
        # 两个子任务的异常都必须被记录，不允许静默丢弃第二个
        self.assertIn("heartbeat-error", joined)
        self.assertIn("monitor-error", joined)


if __name__ == "__main__":
    unittest.main()
