from __future__ import annotations

import threading
import time


class WatchTimeTracker:
    """Accumulates effective watch time using a monotonic local clock.

    Time only accrues while the live-trace heartbeat session is healthy;
    disconnects pause the clock so reconnect stalls never inflate progress.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._accumulated = 0.0
        self._started_at: float | None = None

    def resume(self) -> None:
        with self._lock:
            if self._started_at is None:
                self._started_at = time.monotonic()

    def pause(self) -> None:
        with self._lock:
            if self._started_at is not None:
                self._accumulated += max(0.0, time.monotonic() - self._started_at)
                self._started_at = None

    def elapsed_seconds(self) -> float:
        with self._lock:
            current = self._accumulated
            if self._started_at is not None:
                current += max(0.0, time.monotonic() - self._started_at)
            return current

    def reset(self) -> None:
        with self._lock:
            self._accumulated = 0.0
            self._started_at = None


def estimate_remaining_seconds(
    elapsed_seconds: float,
    cur_value: int | float,
    limit_value: int | float,
) -> float | None:
    """Rough remaining time estimate based on observed server progress rate.

    Rate (minutes of server progress per minute watched locally) is derived
    from the current progress and local elapsed time; falls back to 1:1 when
    the rate cannot be trusted.
    """
    remaining_minutes = float(limit_value) - float(cur_value)
    if remaining_minutes <= 0:
        return 0.0
    elapsed_minutes = elapsed_seconds / 60.0
    if elapsed_minutes >= 1.0 and float(cur_value) > 0:
        rate = float(cur_value) / elapsed_minutes
        if rate > 0.05:
            return remaining_minutes / rate * 60.0
    return remaining_minutes * 60.0
