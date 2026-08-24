from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, patch

from overwatch_drops_miner.config import MinerConfig
from overwatch_drops_miner.miner import BilibiliWatchTimeMiner, SessionPlan


def config() -> MinerConfig:
    return MinerConfig(cookie="cookie", room_ids=[1])


class MinerLoginGuardTest(unittest.TestCase):
    def test_invalid_initial_cookie_does_not_start_sessions(self) -> None:
        miner = BilibiliWatchTimeMiner(config())
        miner._probe_login = AsyncMock(return_value=(None, ""))
        with patch.object(miner, "_thread_entry") as thread_entry:
            with self.assertRaisesRegex(RuntimeError, "Cookie 已失效"):
                miner.run()
        thread_entry.assert_not_called()
        self.assertTrue(miner.login_invalidated)

    def test_watchdog_stops_on_explicit_logout(self) -> None:
        miner = BilibiliWatchTimeMiner(config())
        miner._probe_login = AsyncMock(
            side_effect=[(42, "user"), (None, "")]
        )

        def thread_entry(*_args) -> None:
            miner._stop_event.wait(timeout=2)

        with patch.object(miner, "_thread_entry", side_effect=thread_entry), patch(
            "overwatch_drops_miner.miner.LOGIN_WATCHDOG_INTERVAL_SECONDS", 0.01
        ):
            miner.run()
        self.assertTrue(miner.login_invalidated)

    def test_watchdog_network_error_does_not_mark_cookie_invalid(self) -> None:
        miner = BilibiliWatchTimeMiner(config())
        calls = 0

        async def probe() -> tuple[int | None, str]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return 42, "user"
            if calls == 2:
                raise OSError("temporary offline")
            miner.stop()
            return 42, "user"

        miner._probe_login = probe  # type: ignore[method-assign]

        def thread_entry(*_args) -> None:
            miner._stop_event.wait(timeout=3)

        with patch.object(miner, "_thread_entry", side_effect=thread_entry), patch(
            "overwatch_drops_miner.miner.LOGIN_WATCHDOG_INTERVAL_SECONDS", 0.01
        ):
            miner.run()
        self.assertGreaterEqual(calls, 3)
        self.assertFalse(miner.login_invalidated)

    def test_run_waits_until_all_session_threads_really_exit(self) -> None:
        miner = BilibiliWatchTimeMiner(config())
        miner._probe_login = AsyncMock(return_value=(42, "user"))
        session_started = threading.Event()
        release_session = threading.Event()

        def thread_entry(*_args) -> None:
            session_started.set()
            release_session.wait(timeout=3)

        run_thread = threading.Thread(target=miner.run)
        with patch.object(miner, "_thread_entry", side_effect=thread_entry):
            run_thread.start()
            self.assertTrue(session_started.wait(timeout=1))
            miner.stop(force=True)

            # The owner must not return and let the GUI report stopped while a
            # session is still alive after its bounded joins.
            run_thread.join(timeout=0.4)
            self.assertTrue(run_thread.is_alive())
            self.assertTrue(any(thread.is_alive() for thread in miner._threads))

            release_session.set()
            run_thread.join(timeout=2)

        self.assertFalse(run_thread.is_alive())
        self.assertEqual(miner._threads, [])


if __name__ == "__main__":
    unittest.main()
