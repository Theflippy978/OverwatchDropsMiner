from __future__ import annotations

import json
import logging
import os
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass, field

from python_sidecar.backend import dpapi
from python_sidecar.backend.paths import get_accounts_path

LOGGER = logging.getLogger(__name__)

# 代理项区间：U+D800..U+DFFF（含高代理 U+DB80..U+DBFF 与低代理 U+DC00..U+DFFF）
_SURROGATE_RANGE = (0xD800, 0xDFFF)
# 除换行/回车/制表外一律剔除的 C0 与 DEL 控制字符。备注是单行文本，
# 控制字符在 UI 里不可见也无法选中，只会造成「看起来对但存的是别的字符」。
_CONTROL_CHARS = frozenset(chr(c) for c in (*range(0x20), 0x7F)) - {"\n", "\r", "\t"}


def sanitize_text(value: object) -> str:
    """把任意来源的文本整理成可安全落盘的字符串。

    剔除两类字符：

    - **孤立代理项**（``U+D800..U+DFFF``）：Python 字符串可以持有它们，
      ``json.dumps(ensure_ascii=False)`` 也容忍，但 strict UTF-8 编码一定抛
      ``UnicodeEncodeError``。典型来源是 stdio 按错误编码解码 UTF-8 字节后，
      surrogateescape 把非法字节兜底成了代理字符。
    - **控制字符**：不可见、无法选中、无法用键盘打出。

    同时做 NFC 归一化，让「同一视觉字符的两种编码」变成同一个字符串——
    否则看起来相同的两个备注在数据库与界面比对时不相等。

    约束：必须**幂等**（清洗两次与一次结果相同），且**不改写正常中文**。
    非字符串输入（None、数字、字典）统一转 str，避免调用方各写一遍判断。
    """
    text = value if isinstance(value, str) else str(value)
    text = unicodedata.normalize("NFC", text)
    return "".join(
        char
        for char in text
        if not (_SURROGATE_RANGE[0] <= ord(char) <= _SURROGATE_RANGE[1])
        and char not in _CONTROL_CHARS
    )


def count_unsafe_chars(value: object) -> int:
    """统计会被 :func:`sanitize_text` 剔除的字符数，用于向用户报告修复量。"""
    text = value if isinstance(value, str) else str(value)
    return sum(
        1
        for char in text
        if _SURROGATE_RANGE[0] <= ord(char) <= _SURROGATE_RANGE[1]
        or char in _CONTROL_CHARS
    )


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
            except UnicodeDecodeError as exc:
                # 文件不是合法 UTF-8，但内容未必丢了。surrogateescape 能把
                # 非法字节原样取回，之后由 sanitize_text 清掉那几个字符，
                # 账号、Cookie、备注都还在。
                #
                # 原实现把它并进 (OSError, ValueError) 走「文件损坏」分支，
                # 直接 os.replace 成 .corrupt-* 并当空库启动 —— 用户视角是
                # 「账号全没了」，而磁盘上还躺着一份完好的备份。
                raw = self._path.read_bytes().decode("utf-8", "surrogateescape")
                LOGGER.warning(
                    "账号文件含 %d 处非法 UTF-8 字节，已按原样读入并清洗，报错为 %s",
                    count_unsafe_chars(raw),
                    exc,
                )
            except OSError as exc:
                self._quarantine(f"账号配置文件无法读取（{exc}）")
                return
            try:
                data = json.loads(raw) if raw.strip() else []
            except ValueError as exc:
                # 到这里才是真正的 JSON 结构损坏
                self._quarantine(f"账号配置文件内容损坏（{exc}）")
                return

            accounts: list[Account] = []
            repaired = 0
            for item in data if isinstance(data, list) else []:
                try:
                    account = Account.from_dict(item)
                except Exception:
                    continue
                # from_dict 只做 str() 强转，不清洗：它也是文件里读出来的入口，
                # 必须在这里补 sanitize_text，否则下面的「已清洗」日志是假的 ——
                # 代理字符会一直留在内存里，直到某次落盘被 errors="replace"
                # 静默替换成 U+FFFD，用户全程看不到任何提示。
                cleaned = sanitize_text(account.remark)
                repaired += count_unsafe_chars(account.remark)
                account.remark = cleaned
                accounts.append(account)
            self._accounts = accounts
            if repaired:
                # 清洗只发生在内存里；落盘留给下一次写操作，避免 load 变成隐式写
                LOGGER.warning(
                    "已清洗 %d 个账号备注中的非法字符，下次保存后写回磁盘", repaired
                )
                # 上面这句日志只有在真正调用 sanitize_text 后才成立。
                # 若哪天删掉了清洗那两行，这段日志就会变成「说了但没做」——
                # 判断依据：内存里 remark 不应还含代理项。

    def _quarantine(self, reason: str) -> None:
        """把无法解析的文件改名备份并以空库启动。

        只在文件**确实无法解析**时调用。调用方负责先尝试 salvage ——
        直接清空会让用户丢账号，代价远大于留一个坏文件。
        """
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = self._path.with_name(f"{self._path.name}.corrupt-{timestamp}")
        try:
            os.replace(self._path, backup_path)
            LOGGER.warning("%s，已备份为 %s", reason, backup_path)
        except OSError:
            LOGGER.warning("%s，且备份失败（%s）", reason, backup_path)
        self._accounts = []

    def _save_locked(self) -> None:
        """原子写入账号文件：先写同目录临时文件，成功后 os.replace 替换。

        - 临时名带 pid：避免双开实例写同一 .tmp 互相交错；
        - flush+fsync：确保 replace 前内容已落盘，掉电不残留半截文件。
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            [account.to_dict() for account in self._accounts],
            ensure_ascii=False,
            indent=2,
        )
        tmp_path = self._path.with_name(f"{self._path.name}.tmp{os.getpid()}")
        try:
            # errors="replace" 是纵深防御。入口（from_dict/add/update）已清洗，
            # 但 payload 还含 encrypted_cookie 等未来新增字段，任何一处漏掉
            # 清洗都会在这里让**整个账号库**不可写——因为这里是全量数组落盘。
            # 替换成 U+FFFD 保留了其余全部内容，优于整体失败。
            with open(tmp_path, "w", encoding="utf-8", errors="replace") as fh:
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
            remark=sanitize_text(remark),
            encrypted_cookie=dpapi.protect(cookie.strip()),
        )
        with self._lock:
            # 先落盘再入内存：落盘失败时不会留下一个只存在于内存、无法写回的
            # 幽灵账号。原实现顺序相反，一次失败后这个账号会永久卡在列表里。
            self._accounts.append(account)
            try:
                self._save_locked()
            except Exception:
                self._accounts.pop()
                raise
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
                    break
            else:
                return None

            # 记录原值用于回滚。原实现直接改内存再落盘，落盘失败不回滚，
            # 于是脏数据永久留在内存里：此后 rename / remove / add 每次都
            # 在同一行失败，一个账号不可写会连累整个账号库不可写，
            # 用户唯一出路是重启进程。
            old_remark = account.remark
            old_cookie = account.encrypted_cookie

            if remark is not None:
                account.remark = sanitize_text(remark)
            if cookie is not None and cookie.strip():
                account.encrypted_cookie = dpapi.protect(cookie.strip())
            try:
                self._save_locked()
            except Exception:
                account.remark = old_remark
                account.encrypted_cookie = old_cookie
                raise
        return account

    def remove(self, account_id: str) -> bool:
        with self._lock:
            before = len(self._accounts)
            remaining = [
                account for account in self._accounts if account.id != account_id
            ]
            removed = len(remaining) < before
            if not removed:
                return False
            # 与 add/update 同口径：先落盘再换内存，落盘失败则回滚。
            # 少了回滚的话，一次写失败就会让「内存里账号没了、磁盘上还在」，
            # 当前会话看起来删掉了，下次启动又冒出来，且此后任何一次成功保存
            # 都会把这次失败的删除悄悄持久化。
            previous = self._accounts
            self._accounts = remaining
            try:
                self._save_locked()
            except Exception:
                self._accounts = previous
                raise
        return True

    def reorder(self, ordered_ids: list[str]) -> bool:
        """按给定顺序重排账号（拖拽排序的落盘入口）。

        **顺序本身就是账号的显示顺序**：`accounts.json` 是有序 JSON 数组，
        `list_accounts()` 原样返回，前端按数组顺序渲染。所以「重排」只是把
        `self._accounts` 换成新顺序再落盘，**没有也不需要额外的 order 字段**
        （加字段会引入「数组顺序与 order 字段不一致时以谁为准」的二义性）。

        **契约（不满足则返回 False 且不落盘）**：
          * `ordered_ids` 必须是当前账号集合的**一个排列** —— 既不缺也不多、无重复。
            刻意**不**放宽成「子集」：放宽后调用方漏传一个账号就会把它静默删掉，
            而用户看到的是「拖了一下，账号没了」。
          * 顺序与当前完全相同时直接返回 True，不做无谓落盘（避免每次拖拽都写盘）。

        与 add/update/remove 同口径：先改内存再落盘，**落盘失败回滚**。
        不回滚的话，一次写失败会让内存顺序与磁盘顺序分叉 ——
        用户当前会话看到新顺序，重启后变回去，且此后任何一次成功保存
        都会把这次失败的顺序悄悄持久化。
        """
        with self._lock:
            current_ids = [account.id for account in self._accounts]
            # 先用 set 查重：等长但「重复一项 + 漏一项」的错配单看长度查不出来
            if len(ordered_ids) != len(set(ordered_ids)):
                return False
            if set(ordered_ids) != set(current_ids):
                return False
            if ordered_ids == current_ids:
                return True

            by_id = {account.id: account for account in self._accounts}
            previous = self._accounts
            self._accounts = [by_id[account_id] for account_id in ordered_ids]
            try:
                self._save_locked()
            except Exception:
                self._accounts = previous
                raise
        return True
