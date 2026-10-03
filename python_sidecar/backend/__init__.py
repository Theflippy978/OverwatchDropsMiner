"""Sidecar 的后端实现（B 站业务逻辑层），由 main.py 以 IPC 方式调用。

目录：
- ``client_parts/``   B 站 API：请求、WBI 签名、任务/奖励解析、扫码登录
- ``browser/``        浏览器自动化与展示层辅助：嗅探、配置读写、文本格式化、
                      worker 生命周期、更新检查
- 顶层模块            挖矿（miner / miner_manager / x25kn_worker）、
                      账号与凭据（accounts / dpapi / paths）、
                      配置（config）、通知（notifier）、工具（utils）

``browser/`` 里没有任何 Qt/GUI 依赖，是纯 Python 逻辑。别按目录名想当然
当成界面代码 —— ``worker_controller`` 是 miner 运行时状态机的依赖，
曾因被误判为「GUI 专用」而差点删掉。
"""

from __future__ import annotations

__all__ = [
    "account_log_context",
    "accounts",
    "async_backend",
    "browser",
    "client",
    "client_parts",
    "config",
    "dpapi",
    "logging_utils",
    "miner",
    "miner_manager",
    "notifier",
    "paths",
    "utils",
    "watch_time_tracker",
    "x25kn_worker",
]