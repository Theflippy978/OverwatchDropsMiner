from __future__ import annotations

import unittest

from overwatch_drops_miner.gui_parts.task_presenter import (
    format_watch_status_line,
)


class WatchStatusLineTest(unittest.TestCase):
    """方案 B 四段状态行：B站认可 / 本地连接 / 预计剩余。"""

    def test_dual_display_with_bili_data(self) -> None:
        line = format_watch_status_line(
            running=True,
            bili_cur_minutes=23.5,
            local_elapsed_seconds=312,  # 5分12秒
            limit_value=120,
        )
        self.assertIn("有效观看(B站): 23.5分钟", line)
        self.assertIn("本地连接: 5分12秒", line)
        self.assertIn("状态: 挂宝中", line)
        # 有数据时预计剩余应给出估算而非 --
        self.assertNotIn("预计剩余: --", line)

    def test_without_bili_data_shows_placeholders(self) -> None:
        line = format_watch_status_line(
            running=True,
            bili_cur_minutes=None,
            local_elapsed_seconds=60,
            limit_value=0.0,
        )
        self.assertIn("有效观看(B站): --", line)
        self.assertIn("本地连接: 1分00秒", line)
        self.assertIn("预计剩余: --", line)

    def test_completed_limit_shows_done(self) -> None:
        line = format_watch_status_line(
            running=True,
            bili_cur_minutes=120,
            local_elapsed_seconds=3600,
            limit_value=120,
        )
        self.assertIn("有效观看(B站): 120分钟", line)
        self.assertIn("预计剩余: 已达标", line)

    def test_paused_state_wording(self) -> None:
        line = format_watch_status_line(
            running=False,
            bili_cur_minutes=10,
            local_elapsed_seconds=600,
            limit_value=120,
        )
        self.assertIn("状态: 已暂停", line)


if __name__ == "__main__":
    unittest.main()
