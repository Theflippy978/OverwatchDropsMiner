"""S4 IPC 并发改造的协议级测试。

覆盖：
1. 请求 id 原样回带（Rust 侧据此路由响应）；
2. 慢命令不阻塞后续命令（两条命令并发执行）；
3. stdin 关闭后进行中的命令仍会写完响应；
4. 异常/非法 JSON 也回带 id（或明确不带）；
5. 事件行（type=event）不带 id；
6. 文本解析 helper（_clamp_int / _normalize_task_ids_text）；
7. 浏览器嗅探单会话守卫（_acquire_sniff / _release_sniff）。

不依赖 PySide6、网络与临时目录。
"""
import asyncio
import importlib
import io
import json
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from python_sidecar import main as sidecar_main  # noqa: E402


class FakeSidecar:
    """记录响应行、可注入延迟的假 sidecar"""

    def __init__(self, delays: dict | None = None) -> None:
        self.lines: list[str] = []
        self._lock = threading.Lock()
        self.delays = delays or {}
        self.started: list[str] = []

    def _write_line(self, text: str) -> None:
        with self._lock:
            self.lines.append(text)

    # 与 PythonSidecar._dumps 保持同一序列化契约（2026-10-02）：
    # run_request 改用它并带异常兜底后，fake 必须提供同名方法，
    # 否则会走进兜底分支并把正常响应替换成「响应序列化/写出失败」。
    def _dumps(self, payload) -> str:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)

    async def handle_command(self, command, params):
        self.started.append(command)
        delay = self.delays.get(command, 0)
        if delay:
            await asyncio.sleep(delay)
        return {"command": command, "params": params}

    def responses(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]


def run_serve(fake, stdin_text: str, timeout: float = 10.0) -> None:
    """用给定 stdin 内容跑一次 serve_requests（跑完即返回）"""

    async def runner():
        await asyncio.wait_for(sidecar_main.serve_requests(fake), timeout=timeout)

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin_text)
    try:
        asyncio.run(runner())
    finally:
        sys.stdin = old_stdin


def test_response_echoes_request_id():
    fake = FakeSidecar()
    run_serve(
        fake,
        json.dumps({"id": 7, "command": "get_accounts", "params": {}}) + "\n",
    )
    assert fake.responses() == [{"command": "get_accounts", "params": {}, "id": 7}]


def test_slow_command_does_not_block_fast_command():
    fake = FakeSidecar(delays={"slow": 0.3})
    lines = (
        "\n".join(
            [
                json.dumps({"id": 1, "command": "slow", "params": {}}),
                json.dumps({"id": 2, "command": "fast", "params": {}}),
            ]
        )
        + "\n"
    )
    run_serve(fake, lines)
    # 后发出的快命令先完成 ⇒ 两条命令是并发执行的，不再是串行 await
    assert [r["id"] for r in fake.responses()] == [2, 1]


def test_in_flight_command_finishes_after_stdin_closes():
    fake = FakeSidecar(delays={"slow": 0.2})
    run_serve(fake, json.dumps({"id": 1, "command": "slow", "params": {}}) + "\n")
    assert fake.responses() == [{"command": "slow", "params": {}, "id": 1}]


def test_error_response_still_echoes_id():
    class BoomSidecar(FakeSidecar):
        async def handle_command(self, command, params):
            raise RuntimeError("boom")

    fake = BoomSidecar()
    run_serve(fake, json.dumps({"id": 3, "command": "x", "params": {}}) + "\n")
    assert fake.responses() == [{"error": "boom", "id": 3}]


def test_invalid_json_reports_error_without_id():
    fake = FakeSidecar()
    run_serve(fake, "this is not json\n")
    responses = fake.responses()
    assert responses == [{"error": "无效的 JSON"}]
    assert "id" not in responses[0]


def test_event_line_has_no_id():
    sidecar = sidecar_main.PythonSidecar.__new__(sidecar_main.PythonSidecar)
    sidecar._stdout_lock = threading.Lock()
    sidecar._event_callbacks = []
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    try:
        sidecar._emit_event("account-state-changed", {"account_id": "a", "running": True})
    finally:
        sys.stdout = old_stdout
    payload = json.loads(captured.getvalue().strip())
    assert payload["type"] == "event"
    assert payload["event"] == "account-state-changed"
    assert payload["data"] == {"account_id": "a", "running": True}
    # 事件行不是命令响应，绝不能带 id（否则 Rust 会当成响应路由）
    assert "id" not in payload


@pytest.mark.parametrize(
    "value,expected",
    [
        ("42", 42),
        ("0", 1),  # 低于下限 → 钳到下限
        ("999", 128),  # 高于上限 → 钳到上限
        ("", 60),  # 空值 → 默认值
        ("abc", 60),  # 非法值 → 默认值
        (None, 60),
    ],
)
def test_clamp_int(value, expected):
    assert sidecar_main._clamp_int(value, 60, 1, 128) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("b, a ,a", "a,b"),
        (" 1 ", "1"),
        ("", ""),
        # 2026-10-02 更正：原期望 "None" 是在保护错误行为 ——
        # str(None) == "None" 会生成一个名为 "None" 的任务 ID。
        # 函数本身缺 None 防护，已改为返回空串。
        (None, ""),
    ],
)
def test_normalize_task_ids_text(value, expected):
    assert sidecar_main._normalize_task_ids_text(value) == expected


def _bare_sidecar() -> sidecar_main.PythonSidecar:
    """只初始化嗅探守卫所需字段，避免构造整个 sidecar 后端"""
    sidecar = sidecar_main.PythonSidecar.__new__(sidecar_main.PythonSidecar)
    sidecar._sniff_lock = threading.Lock()
    sidecar._sniff_busy = False
    sidecar._sniff_cancel_event = None
    sidecar._sniff_thread_ref = None
    return sidecar


def test_sniff_guard_is_exclusive():
    sidecar = _bare_sidecar()
    assert sidecar._acquire_sniff() is True
    # 第二个并发命令必须被拒绝（不会并发打开两个浏览器）
    assert sidecar._acquire_sniff() is False
    sidecar._release_sniff()
    assert sidecar._acquire_sniff() is True


def test_sniff_guard_release_clears_session_refs():
    sidecar = _bare_sidecar()
    cancel_event = threading.Event()
    sidecar._acquire_sniff()
    sidecar._register_sniff(cancel_event)
    assert sidecar._sniff_cancel_event is cancel_event
    sidecar._register_sniff_thread(threading.current_thread())
    assert sidecar._sniff_thread_ref is threading.current_thread()
    sidecar._release_sniff()
    assert sidecar._sniff_busy is False
    assert sidecar._sniff_cancel_event is None
    assert sidecar._sniff_thread_ref is None


# --- _drive_sniff_session：Cookie 捕获 / 房间号 / 任务ID 三种模式共用的骨架 ---
# 这些断言覆盖重构前两份抄写不一致的行为，现在骨架只剩一份。


@pytest.fixture
def fake_sniffer(monkeypatch):
    """替换 start_browser_sniff，返回记录到的调用参数与可控的 done 信号。

    真实实现要拉起 Selenium（5-15s）且依赖本机装了 Chrome，测试里不可行。
    """
    calls: list[dict] = []

    def _install(behaviour):
        def _fake_start(**kwargs):
            calls.append(kwargs)
            return behaviour(kwargs)

        module = importlib.import_module(
            "python_sidecar.backend.browser.browser_sniffer"
        )
        monkeypatch.setattr(module, "start_browser_sniff", _fake_start)
        return calls

    return _install


def test_drive_sniff_returns_none_when_result_ready(fake_sniffer):
    """回调 set 了 done → 骨架返回 None，由调用方读自己的结果容器"""
    sidecar = _bare_sidecar()
    done = threading.Event()

    def _behaviour(kwargs):
        # 模拟嗅探线程回调：写结果并唤醒 waiter
        kwargs["on_result"]({"room_id": 123})
        done.set()
        return threading.current_thread()

    fake_sniffer(_behaviour)

    async def _run():
        return await sidecar._drive_sniff_session(
            action="浏览器嗅探",
            start_kwargs={"on_result": lambda payload: None},
            done=done,
            timeout_error="超时了",
        )

    assert asyncio.run(_run()) is None


def test_drive_sniff_returns_error_dict_on_timeout(fake_sniffer):
    """嗅探线程什么都不做 → 超时 → 返回调用方给定的 timeout_error"""
    sidecar = _bare_sidecar()
    done = threading.Event()  # 永不被 set

    def _behaviour(kwargs):
        return threading.current_thread()

    fake_sniffer(_behaviour)

    async def _run():
        return await sidecar._drive_sniff_session(
            action="浏览器嗅探",
            start_kwargs={},
            done=done,
            timeout_error="浏览器操作超时（2 分钟）",
            timeout_seconds=0.05,
        )

    result = asyncio.run(_run())
    assert result == {"error": "浏览器操作超时（2 分钟）"}


def test_drive_sniff_rejects_concurrent_session(fake_sniffer):
    """守卫被占用时直接拒绝，不起浏览器"""
    sidecar = _bare_sidecar()
    sidecar._sniff_busy = True  # 模拟另一条嗅探命令正在跑
    calls = fake_sniffer(lambda kwargs: threading.current_thread())
    done = threading.Event()

    async def _run():
        return await sidecar._drive_sniff_session(
            action="浏览器嗅探",
            start_kwargs={},
            done=done,
            timeout_error="超时了",
        )

    result = asyncio.run(_run())
    assert "error" in result
    assert calls == []  # 关键：没有真的去起浏览器


def test_drive_sniff_releases_guard_and_cancels_in_finally(fake_sniffer):
    """无论成功、超时还是异常，finally 都必须释放守卫并唤醒 waiter"""
    sidecar = _bare_sidecar()
    done = threading.Event()
    seen: dict = {}

    def _behaviour(kwargs):
        seen["cancel"] = kwargs["cancel_event"]
        return threading.current_thread()

    fake_sniffer(_behaviour)

    async def _run():
        return await sidecar._drive_sniff_session(
            action="浏览器嗅探",
            start_kwargs={},
            done=done,
            timeout_error="超时了",
            timeout_seconds=0.05,
        )

    asyncio.run(_run())
    # 守卫已释放（不再 busy）
    assert sidecar._sniff_busy is False
    assert sidecar._sniff_cancel_event is None
    # cancel_event 必须被 set —— 否则嗅探线程的 driver.quit() 永远不执行
    assert seen["cancel"].is_set()
    # done 必须被 set —— 否则 to_thread(done.wait) 的工作线程永久阻塞、拖死退出
    assert done.is_set()


def test_drive_sniff_releases_guard_when_start_raises(fake_sniffer):
    """start_browser_sniff 抛异常时守卫不能泄漏（否则后续命令永远被拒）"""
    sidecar = _bare_sidecar()
    done = threading.Event()

    def _behaviour(kwargs):
        raise RuntimeError("驱动崩了")

    fake_sniffer(_behaviour)

    async def _run():
        return await sidecar._drive_sniff_session(
            action="浏览器捕获",
            start_kwargs={},
            done=done,
            timeout_error="超时了",
        )

    result = asyncio.run(_run())
    assert "error" in result
    assert sidecar._sniff_busy is False
    assert done.is_set()
