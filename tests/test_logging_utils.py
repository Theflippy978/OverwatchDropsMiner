from __future__ import annotations

import logging
import unittest


class _CloseTrackingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def emit(self, record: logging.LogRecord) -> None:
        pass

    def close(self) -> None:
        self.closed = True
        super().close()


class PrettyFormatterTest(unittest.TestCase):
    def test_format_does_not_mutate_record_levelname(self) -> None:
        from overwatch_drops_miner.logging_utils import PrettyFormatter

        record = logging.LogRecord(
            "test.logger",
            logging.WARNING,
            "path",
            1,
            "hello %s",
            ("world",),
            None,
        )
        formatter = PrettyFormatter(verbose=True, use_color=True)
        formatted = formatter.format(record)
        self.assertEqual(record.levelname, "WARNING")
        self.assertIn("hello world", formatted)


class SetupLoggingTest(unittest.TestCase):
    def test_old_handlers_are_closed_on_reset(self) -> None:
        from overwatch_drops_miner.logging_utils import setup_logging

        root = logging.getLogger()
        stale = _CloseTrackingHandler()
        root.addHandler(stale)
        try:
            setup_logging(verbose=False, no_color=True)
            self.assertTrue(stale.closed)
            self.assertNotIn(stale, root.handlers)
        finally:
            for handler in root.handlers[:]:
                root.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
