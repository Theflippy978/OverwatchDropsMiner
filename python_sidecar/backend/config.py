from __future__ import annotations

from dataclasses import dataclass, field

# 线程数 / 总连接数上限。四处必须同源：
#   本文件的 validate()、python_sidecar/main.py 的 MAX_THREAD_COUNT（_clamp_int 用）、
#   src/stores/config.ts 的 MAX_THREAD_COUNT、ConfigForm.vue 输入框的 max 属性。
# 历史上四处出现过 128/256 不一致，后果是「前端允许填 256、保存也成功，
# 启动时才被 validate() 拒」，而错误文案来自深层调用，用户无法关联因果
# （默认 60 线程 × 3 房间 = 180，正好落在两者之间）。
MAX_TOTAL_CONNECTIONS = 256


@dataclass(slots=True)
class MinerConfig:
    cookie: str
    room_ids: list[int]
    thread_count: int = 1
    reconnect_delay_seconds: int = 8
    task_ids: list[str] = field(default_factory=list)
    task_query_interval_seconds: int = 30
    notify_urls: list[str] = field(default_factory=list)
    notify_on_task_complete: bool = True

    def validate(self) -> None:
        if not self.cookie.strip():
            raise ValueError("cookie 不能为空")
        if not self.room_ids:
            raise ValueError("room_ids 不能为空")
        if any(room_id <= 0 for room_id in self.room_ids):
            raise ValueError("room_ids 中存在非法房间号")
        if self.thread_count <= 0:
            raise ValueError("thread_count 必须大于 0")
        if self.thread_count > MAX_TOTAL_CONNECTIONS:
            raise ValueError(f"线程数不能超过 {MAX_TOTAL_CONNECTIONS}")
        if len(self.room_ids) * self.thread_count > MAX_TOTAL_CONNECTIONS:
            raise ValueError(
                f"总连接数（房间数 × 线程数）不能超过 {MAX_TOTAL_CONNECTIONS}"
            )
        if self.reconnect_delay_seconds <= 0:
            raise ValueError("reconnect_delay_seconds 必须大于 0")
        if self.reconnect_delay_seconds > 3600:
            raise ValueError("reconnect_delay_seconds 不能超过 3600")
        if self.task_query_interval_seconds <= 0:
            raise ValueError("task_query_interval_seconds 必须大于 0")
        if self.task_query_interval_seconds > 3600:
            raise ValueError("task_query_interval_seconds 不能超过 3600")
