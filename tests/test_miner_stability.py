from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from python_sidecar.backend.config import MinerConfig
from python_sidecar.backend.miner import BilibiliWatchTimeMiner, SessionPlan


def config(room_ids: list[int] | None = None, thread_count: int = 1) -> MinerConfig:
    return MinerConfig(
        cookie="cookie",
        room_ids=room_ids if room_ids is not None else [1],
        thread_count=thread_count,
    )


class FakeFailingClient:
    """get_self_info 抛异常的假客户端，模拟网络抖动。"""

    def __init__(self, cookie: str) -> None:
        self.cookie = cookie

    def update_cookie(self, cookie: str) -> None:
        self.cookie = cookie

    async def get_self_info(self):  # type: ignore[no-untyped-def]
        raise OSError("网络抖动")

    async def close(self) -> None:
        return None


class FakeNoneUidClient:
    """get_self_info 返回 (None, "") 的假客户端。"""

    def __init__(self, cookie: str) -> None:
        self.cookie = cookie

    def update_cookie(self, cookie: str) -> None:
        self.cookie = cookie

    async def get_self_info(self):  # type: ignore[no-untyped-def]
        return None, ""

    async def close(self) -> None:
        return None


class MinerStabilityTest(unittest.TestCase):
    def test_connection_thread_failure_does_not_stop_others(self) -> None:
        miner = BilibiliWatchTimeMiner(config())

        with patch(
            "python_sidecar.backend.miner.BilibiliClient", FakeFailingClient
        ):
            # 直接调用 _thread_entry 层面：连接内异常应被吞掉并正常返回，
            # 绝不能把全局 stop_event 置位拖垮其他房间/连接。
            miner._thread_entry(SessionPlan(1, 1), 1)

        self.assertFalse(miner._stop_event.is_set())
        self.assertFalse(miner.login_invalidated)

    def test_uid_none_skips_worker_without_zero_uid(self) -> None:
        miner = BilibiliWatchTimeMiner(config())
        constructed_workers: list[object] = []

        class RecordingWorker:
            def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
                constructed_workers.append(kwargs)

            async def run_forever(self) -> None:
                await asyncio.Event().wait()

            async def stop(self) -> None:
                return None

        miner._uid = None

        with patch(
            "python_sidecar.backend.miner.BilibiliClient", FakeNoneUidClient
        ), patch("python_sidecar.backend.miner.X25KnWorker", RecordingWorker):
            miner._thread_entry(SessionPlan(1, 1), 1)

        # uid 为 None 时该连接直接退出，绝不以 uid=0 创建 worker。
        self.assertEqual(constructed_workers, [])
        self.assertIsNone(miner.uid)


class ConfigTotalLimitTest(unittest.TestCase):
    def test_validate_rejects_over_128_threads(self) -> None:
        cfg = config(thread_count=129)
        with self.assertRaisesRegex(ValueError, "线程数不能超过 128"):
            cfg.validate()

    def test_validate_rejects_total_connections_over_128(self) -> None:
        cfg = config(room_ids=[1, 2], thread_count=65)
        with self.assertRaisesRegex(
            ValueError, "总连接数（房间数 × 线程数）不能超过 128"
        ):
            cfg.validate()

    def test_validate_accepts_boundary_128(self) -> None:
        # 边界：单房间 128 线程 与 多房间乘积恰好 128 均应通过。
        config(room_ids=[1], thread_count=128).validate()
        config(room_ids=[1, 2], thread_count=64).validate()


if __name__ == "__main__":
    unittest.main()
