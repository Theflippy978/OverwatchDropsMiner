from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from python_sidecar.backend.watch_time_tracker import (
    WatchTimeTracker,
    estimate_remaining_seconds,
)


class WatchTimeTrackerTest(unittest.TestCase):
    def test_accumulates_only_while_resumed(self) -> None:
        tracker = WatchTimeTracker()
        self.assertEqual(tracker.elapsed_seconds(), 0.0)

        tracker.resume()
        time.sleep(0.05)
        running = tracker.elapsed_seconds()
        self.assertGreater(running, 0.0)

        tracker.pause()
        paused_total = tracker.elapsed_seconds()
        time.sleep(0.05)
        self.assertEqual(tracker.elapsed_seconds(), paused_total)

    def test_resume_is_idempotent(self) -> None:
        tracker = WatchTimeTracker()
        tracker.resume()
        time.sleep(0.03)
        first = tracker.elapsed_seconds()
        tracker.resume()
        time.sleep(0.03)
        second = tracker.elapsed_seconds()
        self.assertGreaterEqual(second, first)
        tracker.pause()

    def test_pause_without_resume_is_safe(self) -> None:
        tracker = WatchTimeTracker()
        tracker.pause()
        self.assertEqual(tracker.elapsed_seconds(), 0.0)

    def test_reset_clears_accumulation(self) -> None:
        tracker = WatchTimeTracker()
        tracker.resume()
        time.sleep(0.03)
        tracker.reset()
        self.assertEqual(tracker.elapsed_seconds(), 0.0)


class EstimateRemainingTest(unittest.TestCase):
    def test_completed_task_returns_zero(self) -> None:
        self.assertEqual(estimate_remaining_seconds(600.0, 120, 120), 0.0)
        self.assertEqual(estimate_remaining_seconds(600.0, 130, 120), 0.0)

    def test_falls_back_to_one_to_one_rate_without_progress(self) -> None:
        remaining = estimate_remaining_seconds(0.0, 0, 60)
        self.assertEqual(remaining, 3600.0)

    def test_uses_observed_rate_when_available(self) -> None:
        # 10 分钟本地观看换来 20 分钟服务器进度 → 速率 2.0，
        # 剩余 60 分钟任务 → 预计 30 分钟。
        remaining = estimate_remaining_seconds(600.0, 20, 80)
        self.assertAlmostEqual(remaining, 1800.0, delta=1.0)

    def test_ignores_absurd_rate(self) -> None:
        # 速率低于 0.05 时回退 1:1。
        remaining = estimate_remaining_seconds(100000.0, 1, 60)
        self.assertEqual(remaining, 59 * 60.0)


if __name__ == "__main__":
    unittest.main()
