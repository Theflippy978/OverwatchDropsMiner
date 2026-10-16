from __future__ import annotations

from dataclasses import dataclass, field

from python_sidecar.backend.constants import (
    RECONNECT_DELAY_DEFAULT_SECONDS,
    RECONNECT_DELAY_MAX_SECONDS,
    TASK_QUERY_INTERVAL_DEFAULT_SECONDS,
    TASK_QUERY_INTERVAL_MAX_SECONDS,
)

# 线程数 / 总连接数上限。同源落点：
#   本文件（定义处）、python_sidecar/main.py（import 本常量做 _clamp_int）、
#   前端 src/lib/config-limits.ts（config.ts 钳制 + ConfigForm.vue 输入框的 max
#   都从它取，跨语言无法共用一个文件，所以各留一份）。
# 历史上这几处出现过 128/256 不一致，后果是「前端允许填 256、保存也成功，
# 启动时才被 validate() 拒」，而错误文案来自深层调用，用户无法关联因果
# （默认 60 线程 × 3 房间 = 180，正好落在两者之间）。
MAX_TOTAL_CONNECTIONS = 256


@dataclass(slots=True)
class MinerConfig:
    cookie: str
    room_ids: list[int]
    thread_count: int = 1
    reconnect_delay_seconds: int = RECONNECT_DELAY_DEFAULT_SECONDS
    task_ids: list[str] = field(default_factory=list)
    task_query_interval_seconds: int = TASK_QUERY_INTERVAL_DEFAULT_SECONDS
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
        if self.reconnect_delay_seconds > RECONNECT_DELAY_MAX_SECONDS:
            raise ValueError(
                f"reconnect_delay_seconds 不能超过 {RECONNECT_DELAY_MAX_SECONDS}"
            )
        # 这里只校验「>0 且 ≤ 上限」，**不校验下限 10**：
        # 还有一条构造 MinerConfig 的路径（main.py 里直接取 data 字段、
        # 不经过 _clamp_int）传的是用户配置原值，加上限会让本来能跑的旧配置
        # 突然报错。下限由钳制点负责，validate 只做硬边界。
        if self.task_query_interval_seconds <= 0:
            raise ValueError("task_query_interval_seconds 必须大于 0")
        if self.task_query_interval_seconds > TASK_QUERY_INTERVAL_MAX_SECONDS:
            raise ValueError(
                f"task_query_interval_seconds 不能超过 {TASK_QUERY_INTERVAL_MAX_SECONDS}"
            )
