from __future__ import annotations

import unittest

from overwatch_drops_miner.gui_parts.worker_controller import WorkerController
from overwatch_drops_miner.miner_manager import AccountMinerManager, _AccountSession


class FakeStopMiner:
    def __init__(self) -> None:
        self.stop_calls: list[bool] = []

    def stop(self, *, force: bool = False) -> None:
        self.stop_calls.append(force)


class MinerManagerStopAllTest(unittest.TestCase):
    def test_stop_all_skips_none_miner_session(self) -> None:
        manager = AccountMinerManager(lambda cookie: object())

        stopped_session = _AccountSession(
            controller=WorkerController(), tracker=None  # type: ignore[arg-type]
        )
        fake_miner = FakeStopMiner()
        stopped_session.controller.miner = fake_miner

        none_session = _AccountSession(
            controller=WorkerController(), tracker=None  # type: ignore[arg-type]
        )

        manager._sessions["none-miner"] = none_session
        manager._sessions["normal"] = stopped_session

        manager.stop_all()
        self.assertEqual(fake_miner.stop_calls, [False])

        manager.stop_all(force=True)
        self.assertEqual(fake_miner.stop_calls, [False, True])


if __name__ == "__main__":
    unittest.main()
