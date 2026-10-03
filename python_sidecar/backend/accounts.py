from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

from python_sidecar.backend import dpapi
from python_sidecar.backend.paths import get_accounts_path

LOGGER = logging.getLogger(__name__)


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
            except (OSError, ValueError) as exc:
                # 损坏文件先改名备份，避免下次保存时被永久覆盖
                timestamp = time.strftime("%Y%m%d-%H%M%S")
                backup_path = self._path.with_name(
                    f"{self._path.name}.corrupt-{timestamp}"
                )
                try:
                    os.replace(self._path, backup_path)
                    LOGGER.warning(
                        "账号配置文件损坏，已备份为 %s：%s", backup_path, exc
                    )
                except OSError:
                    LOGGER.warning(
                        "账号配置文件损坏且备份失败（%s）：%s", backup_path, exc
                    )
                self._accounts = []
                return
            accounts = []
            for item in data if isinstance(data, list) else []:
                try:
                    accounts.append(Account.from_dict(item))
                except Exception:
                    continue
            self._accounts = accounts

    def _save_locked(self) -> None:
        """原子写入账号文件：先写同目录临时文件，成功后 os.replace 替换。

        - 临时名带 pid（B-2/Z-5）：避免双开实例写同一 .tmp 互相交错；
        - flush+fsync（B-2）：确保 replace 前内容已落盘，掉电不残留半截文件。
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [account.to_dict() for account in self._accounts],
            ensure_ascii=False,
            indent=2,
        )
        tmp_path = self._path.with_name(f"{self._path.name}.tmp{os.getpid()}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def save(self) -> None:
        with self._lock:
            self._save_locked()

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
            self._save_locked()
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
            self._save_locked()
        return account

    def remove(self, account_id: str) -> bool:
        with self._lock:
            before = len(self._accounts)
            self._accounts = [
                account for account in self._accounts if account.id != account_id
            ]
            removed = len(self._accounts) < before
            if removed:
                self._save_locked()
        return removed
