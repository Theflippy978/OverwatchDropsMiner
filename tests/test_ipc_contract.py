"""IPC 契约测试：Rust 注册的命令集合必须与 sidecar 处理的命令集合完全一致。

历史教训（cc764c9 之前）：sidecar 有 27 条命令，而 `src-tauri/src/main.rs` 的
`generate_handler!` 只注册了 19 条，缺 export_config / import_config /
detect_browsers / sync_config_to_miners / shutdown / check_update /
update_notify_urls / stop_all。这类偏差在运行期表现为「前端调用合法、
sidecar 却没有对应实现」或反之，静态断言可以第一时间拦住。

不依赖 PySide6、网络、临时目录。
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_RS = REPO_ROOT / "src-tauri" / "src" / "main.rs"
SIDECAR_MAIN = REPO_ROOT / "python_sidecar" / "main.py"


def rust_registered_commands() -> set[str]:
    text = MAIN_RS.read_text(encoding="utf-8")
    match = re.search(r"generate_handler!\s*\[(.*?)\]", text, re.S)
    assert match, "src-tauri/src/main.rs 里找不到 tauri::generate_handler! 列表"
    return set(re.findall(r"commands::([a-z0-9_]+)", match.group(1)))


def sidecar_handled_commands() -> set[str]:
    text = SIDECAR_MAIN.read_text(encoding="utf-8")
    match = re.search(r"handlers = \{(.*?)\n\s{8}\}", text, re.S)
    assert match, "python_sidecar/main.py 里找不到 handlers 字典"
    return set(re.findall(r'"([a-z0-9_]+)":\s*self\._', match.group(1)))


def test_rust_and_sidecar_command_sets_match():
    rust = rust_registered_commands()
    python = sidecar_handled_commands()
    assert rust == python, (
        f"仅 Rust 注册: {sorted(rust - python)}；"
        f"仅 sidecar 处理: {sorted(python - rust)}"
    )


def test_command_sets_are_not_empty():
    # 防止正则失效（例如把 main.rs 改成 use commands::* 形式）后测试静默通过
    rust = rust_registered_commands()
    python = sidecar_handled_commands()
    assert len(rust) >= 25, f"解析出的 Rust 命令数异常: {sorted(rust)}"
    assert len(python) >= 25, f"解析出的 sidecar 命令数异常: {sorted(python)}"


def test_progress_key_contract():
    """Rust 从响应里读 "progress"，sidecar 必须用同名键写进度（曾经的键错配 bug）。"""
    rust_text = (REPO_ROOT / "src-tauri" / "src" / "commands.rs").read_text(encoding="utf-8")
    sidecar_text = SIDECAR_MAIN.read_text(encoding="utf-8")
    assert 'resp.get("progress")' in rust_text
    assert '"progress": progress' in sidecar_text
