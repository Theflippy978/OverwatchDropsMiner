from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field

from overwatch_drops_miner import dpapi
from overwatch_drops_miner.paths import get_accounts_path


@dataclass(slots=True)
class Account:
    id: str
    remark: str
    encrypted_cookie: str
    created_at: float = field(default_factory=time.time)

    def cookie(self) -> str:
        return dpapi.unprotect(self.encrypted_cookie)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "remark": self.remark,
            "encrypted_cookie": self.encrypted_cookie,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Account":
        return cls(
            id=str(data.get("id", "")),
            remark=str(data.get("remark", "")),
            encrypted_cookie=str(data.get("encrypted_cookie", "")),
            created_at=float(data.get("created_at", 0.0)),
        )


class AccountStore:
    """Persist accounts (remark + DPAPI-encrypted cookie) to a local JSON file."""

    def __init__(self, path=None) -> None:
        self._path = path if path is not None else get_accounts_path()
        self._lock = threading.Lock()
        self._accounts: list[Account] = []
        self.load()

    @property
    def path(self):
        return self._path

    def load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._accounts = []
                return
            try:
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw) if raw.strip() else []
            except (OSError, json.JSONDecodeError):
                self._accounts = []
                return
            accounts = []
            for item in data if isinstance(data, list) else []:
                try:
                    accounts.append(Account.from_dict(item))
                except Exception:
                    continue
            self._accounts = accounts

    def save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                [account.to_dict() for account in self._accounts],
                ensure_ascii=False,
                indent=2,
            )
            self._path.write_text(payload, encoding="utf-8")

    def list_accounts(self) -> list[Account]:
        with self._lock:
            return list(self._accounts)

    def get(self, account_id: str) -> Account | None:
        with self._lock:
            for account in self._accounts:
                if account.id == account_id:
                    return account
        return None

    def add(self, cookie: str, remark: str = "") -> Account:
        account = Account(
            id=uuid.uuid4().hex,
            remark=remark.strip(),
            encrypted_cookie=dpapi.protect(cookie.strip()),
        )
        with self._lock:
            self._accounts.append(account)
        self.save()
        return account

    def update(
        self,
        account_id: str,
        *,
        remark: str | None = None,
        cookie: str | None = None,
    ) -> Account | None:
        with self._lock:
            for account in self._accounts:
                if account.id == account_id:
                    if remark is not None:
                        account.remark = remark.strip()
                    if cookie is not None and cookie.strip():
                        account.encrypted_cookie = dpapi.protect(cookie.strip())
                    break
            else:
                return None
        self.save()
        return account

    def remove(self, account_id: str) -> bool:
        with self._lock:
            before = len(self._accounts)
            self._accounts = [
                account for account in self._accounts if account.id != account_id
            ]
            removed = len(self._accounts) < before
        if removed:
            self.save()
        return removed
