from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

_context = threading.local()


def set_current_account(account_id: str) -> None:
    _context.account_id = account_id


def get_current_account() -> str | None:
    return getattr(_context, "account_id", None)


def clear_current_account() -> None:
    _context.account_id = None


@contextmanager
def account_scope(account_id: str | None) -> Iterator[None]:
    """临时把日志归到某个账号，退出时恢复原值。

    用于那些**不属于账号自身线程**、却要为该账号发日志的位置
    （如 miner_manager 在 IPC 处理线程里打印「挂宝已启动」）。
    没有它这些日志的 account_id 是 None，前端按账号过滤时整段丢失。
    """
    previous = get_current_account()
    if account_id:
        set_current_account(account_id)
    try:
        yield
    finally:
        if previous is None:
            clear_current_account()
        else:
            set_current_account(previous)
