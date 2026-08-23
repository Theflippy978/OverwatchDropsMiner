from __future__ import annotations

import logging
import queue

from overwatch_drops_miner.account_log_context import get_current_account


class QueueLogHandler(logging.Handler):
    """Routes log lines to the GUI queue tagged with the owning account."""

    def __init__(self, q: "queue.Queue[tuple[str | None, str]]") -> None:
        super().__init__()
        self.q = q

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put((get_current_account(), self.format(record)))
        except Exception:
            self.handleError(record)
