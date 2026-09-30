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
        (None, "None"),
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
