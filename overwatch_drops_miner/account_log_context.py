from __future__ import annotations

import threading

_context = threading.local()


def set_current_account(account_id: str) -> None:
    _context.account_id = account_id


def get_current_account() -> str | None:
    return getattr(_context, "account_id", None)


def clear_current_account() -> None:
    _context.account_id = None
