"""sidecar 添加账号 / 启动登录探测的 get_self_info 契约测试（P0 回归）。

背景：`BilibiliClient.get_self_info()` 返回的是 `(uid | None, uname)` 元组
（契约见 `python_sidecar.backend/client_parts/profile.py:parse_self_info`），
但 `python_sidecar/main.py` 曾按 dict 消费，导致 `uid` 恒为 None：
- `_add_account` 无条件报「无法获取用户信息，Cookie 可能已失效」（三条添加入口全挂）
- `_start_miner` 无条件报「Cookie 已失效，无法启动」

本文件把该契约钉死，防止 dict/tuple 漂移再次发生。
"""
import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from python_sidecar import main as sidecar_main  # noqa: E402


class FakeAccountStore:
    def __init__(self) -> None:
        self._seq = 0
        self.accounts: dict[str, SimpleNamespace] = {}

    # 签名须与真实 AccountStore.add(cookie, remark="") 一致。
    # 2026-10-02 起 _add_account 直接带 remark 调用（此前是 add → update
    # 两次落盘，磁盘上会短暂存在 remark="" 的中间态）。
    def add(self, cookie: str, remark: str = "") -> SimpleNamespace:
        self._seq += 1
        acc = SimpleNamespace(id=f"acc{self._seq}", remark=remark.strip())
        # 真实 AccountStore 的 cookie 是方法，实例属性直接挂 lambda（不绑定 self）
        acc.cookie = lambda: cookie
        self.accounts[acc.id] = acc
        return acc

    def update(self, account_id: str, *, remark: str | None = None) -> SimpleNamespace | None:
        acc = self.accounts.get(account_id)
        if acc is None:
            return None
        if remark is not None:
            acc.remark = remark
        return acc

    def get(self, account_id: str) -> SimpleNamespace | None:
        return self.accounts.get(account_id)


def make_sidecar() -> sidecar_main.PythonSidecar:
    """绕过 __init__ 的轻量 sidecar（与 test_sidecar_ipc 的做法一致）"""
    sidecar = sidecar_main.PythonSidecar.__new__(sidecar_main.PythonSidecar)
    sidecar.account_store = FakeAccountStore()
    sidecar.miner_manager = None
    sidecar._event_callbacks = []
    sidecar._stdout_lock = threading.Lock()
    sidecar._emit_event = lambda *a, **k: None
    return sidecar


def _patch_client(monkeypatch, self_info) -> None:
    class FakeClient:
        def __init__(self, cookie: str) -> None:
            self.cookie = cookie

        async def get_self_info(self):
            if isinstance(self_info, Exception):
                raise self_info
            return self_info

        async def close(self) -> None:
            return None

    monkeypatch.setattr("python_sidecar.backend.client.BilibiliClient", FakeClient)


# ---------------------------------------------------------------- _add_account


def test_add_account_accepts_tuple(monkeypatch):
    """正常路径：get_self_info 返回 (uid, uname) 元组 → 添加成功且 remark=uname"""
    _patch_client(monkeypatch, (42, "tester"))
    sidecar = make_sidecar()
    result = asyncio.run(sidecar._add_account({"cookie": "SESSDATA=x; DedeUserID=1"}))
    assert "error" not in result
    assert result["remark"] == "tester"
    assert result["running"] is False
    assert "acc1" in sidecar.account_store.accounts


def test_add_account_rejects_unlogged_tuple(monkeypatch):
    """未登录路径：(None, \"\") → 明确的未登录文案（不是空白、不是崩溃）

    2026-10-02 起 _add_account 与 _start_miner 共用 _probe_identity，
    失败原因作为括号补充跟在主文案后面，便于区分「网络异常」与「Cookie 失效」。
    """
    _patch_client(monkeypatch, (None, ""))
    sidecar = make_sidecar()
    result = asyncio.run(sidecar._add_account({"cookie": "SESSDATA=bad"}))
    assert "无法获取用户信息" in result["error"]
    assert "Cookie 可能已失效或未登录" in result["error"]
    assert sidecar.account_store.accounts == {}


def test_add_account_reports_missing_uid_with_uname(monkeypatch):
    """半异常路径：拿到 uname 但 uid 缺失 → 单独文案，便于区分真未登录"""
    _patch_client(monkeypatch, (None, "tester"))
    sidecar = make_sidecar()
    result = asyncio.run(sidecar._add_account({"cookie": "SESSDATA=x"}))
    assert "用户 ID 缺失" in result["error"]
    assert sidecar.account_store.accounts == {}


def test_add_account_rejects_non_tuple_as_unlogged(monkeypatch):
    """防御路径：非 tuple（如误改回 dict）一律按未登录拒绝，不得误添加"""
    _patch_client(monkeypatch, {"uid": 42, "uname": "tester"})
    sidecar = make_sidecar()
    result = asyncio.run(sidecar._add_account({"cookie": "SESSDATA=x"}))
    assert "error" in result
    assert sidecar.account_store.accounts == {}


def test_add_account_reports_network_error(monkeypatch):
    """网络异常路径：异常原因必须透出，不得吞掉"""
    _patch_client(monkeypatch, RuntimeError("connect timeout"))
    sidecar = make_sidecar()
    result = asyncio.run(sidecar._add_account({"cookie": "SESSDATA=x"}))
    assert "无法获取用户信息" in result["error"]
    assert "connect timeout" in result["error"]


def test_add_account_requires_cookie():
    sidecar = make_sidecar()
    result = asyncio.run(sidecar._add_account({"cookie": ""}))
    assert result == {"error": "Cookie 不能为空"}


# ---------------------------------------------------------------- _start_miner


class FakeManager:
    def __init__(self) -> None:
        self.started: list[str] = []

    def is_running(self, account_id: str) -> bool:
        return False

    def start(self, account) -> bool:
        self.started.append(account.id)
        return True

    def poll_shutdown(self, account_id: str) -> str:
        return "running"


class FakeConfig:
    def validate(self) -> None:
        return None


def _startable_sidecar(monkeypatch, self_info) -> tuple:
    _patch_client(monkeypatch, self_info)
    sidecar = make_sidecar()
    account = sidecar.account_store.add("SESSDATA=x; DedeUserID=1")
    sidecar.miner_manager = FakeManager()
    sidecar._build_config = lambda cookie: FakeConfig()
    return sidecar, account


def test_start_miner_accepts_tuple(monkeypatch):
    """登录探测返回 (uid, uname) → 正常启动"""
    sidecar, account = _startable_sidecar(monkeypatch, (42, "tester"))
    result = asyncio.run(sidecar._start_miner({"account_id": account.id}))
    assert "error" not in result
    assert sidecar.miner_manager.started == [account.id]


def test_start_miner_rejects_unlogged_tuple(monkeypatch):
    """登录探测返回 (None, \"\") → 启动被拒且文案明确（需重试 2 次，各 1 秒间隔）"""
    sidecar, account = _startable_sidecar(monkeypatch, (None, ""))
    result = asyncio.run(sidecar._start_miner({"account_id": account.id}))
    assert "error" in result
    assert "Cookie 已失效或未登录" in result["error"]
    assert sidecar.miner_manager.started == []


def test_start_miner_rejects_non_tuple(monkeypatch):
    """防御路径：dict 契约漂移时同样按未登录拒绝（这正是曾经的 P0 bug 形态）"""
    sidecar, account = _startable_sidecar(monkeypatch, {"uid": 42, "uname": "tester"})
    result = asyncio.run(sidecar._start_miner({"account_id": account.id}))
    assert "error" in result
    assert sidecar.miner_manager.started == []
