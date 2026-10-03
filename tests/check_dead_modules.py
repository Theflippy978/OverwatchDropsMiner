"""死代码门禁：检测「定义了却无任何引用方」的模块。

背景（2026-10-02）：
`python_sidecar.backend/` 里曾有 3469 行死代码 —— 15 个 `gui_parts/*` 模块
加一个 `gui.py`（PySide6 旧 GUI）。它们互相引用形成闭环，看上去有引用方，
实则整块与 sidecar 无关。更危险的是 `gui_parts/worker_controller` 曾被误判为
"GUI 专用"差点删除，而它实际是活代码（`miner_manager` 依赖其状态机）。

做法：用 AST 做可达性分析 —— 从活入口（`python_sidecar/main.py` + 本目录下
全部测试）出发 BFS，标记可达模块；包内文件里剩下的就是无引用方的死代码。

当前只**报告**不阻断（死代码本身不算错误），CI 里作为 informational 步骤
运行；等存量彻底清零后可改成阻断。

为什么放在 tests/ 而不叫 test_*.py：
它是一次性扫描器而非断言型用例（死代码为零是常态，重复跑没有增量价值），
用非 test_ 前缀可避免 pytest 每次都收集它。
"""

from __future__ import annotations

import ast
import sys
from collections import deque
from pathlib import Path

# 本文件位于 tests/ 下，故仓库根是 parents[1]
# （原先放在仓库根的 tools/ 时也是 parents[1]，迁移后语义不变）
REPO_ROOT = Path(__file__).resolve().parents[1]
SIDECAR_ROOT = REPO_ROOT / "python_sidecar"
PKG_ROOT = SIDECAR_ROOT / "backend"
SRC_ROOT = SIDECAR_ROOT
TESTS_ROOT = Path(__file__).resolve().parent

# 活入口：sidecar 主程序 + 本目录下全部测试文件
ENTRY_POINTS = [SRC_ROOT / "main.py"] + sorted(TESTS_ROOT.glob("*.py"))


def _module_name(path: Path) -> str:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve(module: str, anchor: Path) -> Path | None:
    """把 import 语句里的模块名解析成仓库内的 .py 路径。

    模块名形如 `python_sidecar.backend.accounts`，而文件在 `python_sidecar/backend/`。
    注意 `PKG_ROOT.name` 现在是 ``backend``（不是顶层包名），顶层包名要取
    `SIDECAR_ROOT.name`。不能直接拼到 PKG_ROOT 之下 —— 那会得到
    `python_sidecar/backend/backend/accounts.py`。必须先逐级剥前缀。
    """
    parts = module.split(".")
    roots = []
    if parts and parts[0] == SIDECAR_ROOT.name:
        rest = parts[1:]
        if rest and rest[0] == PKG_ROOT.name:
            roots.append((PKG_ROOT, rest[1:]))
        else:
            roots.append((SIDECAR_ROOT, rest))
    for base, rest in roots:
        if not rest:
            candidate_init = base / "__init__.py"
            return candidate_init if candidate_init.exists() else None
        rel = Path(*rest)
        candidate = base / rel.with_suffix(".py")
        if candidate.exists():
            return candidate
        pkg_init = base / rel / "__init__.py"
        if pkg_init.exists():
            return pkg_init
    return None


def collect_imports(path: Path) -> set[str]:
    """解析单个文件的绝对 import（只认 level==0 的 from-import 与 import）"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
            # from pkg import mod —— 也记录 pkg.mod，便于按文件粒度 BFS
            for alias in node.names:
                modules.add(f"{node.module}.{alias.name}")
    return modules


def reachable_modules() -> set[Path]:
    """从活入口做 BFS，返回所有可达的 .py 路径"""
    seen: set[Path] = set()
    queue = deque(p for p in ENTRY_POINTS if p.exists())
    while queue:
        current = queue.popleft()
        if current in seen or not current.exists():
            continue
        seen.add(current)
        for module in collect_imports(current):
            resolved = _resolve(module, current)
            if resolved and resolved not in seen:
                queue.append(resolved)
    return seen


def main() -> int:
    reachable = reachable_modules()
    # 只扫 backend/ 与 sidecar 自身的模块（main.py 是入口，已在活入口里）。
    # 注意 SRC_ROOT.rglob 会把 backend/ 再扫一遍，故显式排除避免重复计数。
    package_files = {
        p for p in SIDECAR_ROOT.rglob("*.py") if "__pycache__" not in p.parts
    }

    # 完全不可达的包内文件 = 死代码
    dead = sorted(package_files - reachable)
    # __init__.py 视为始终可达（包入口）
    dead = [p for p in dead if p.name != "__init__.py"]

    print(f"可达模块: {len(reachable)}")
    print(f"包内文件总数: {len(package_files)}")
    print(f"无引用方（疑似死代码）: {len(dead)}")
    for path in dead:
        rel = path.relative_to(REPO_ROOT)
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        print(f"  DEAD {rel} ({lines} 行)")

    if dead:
        print(
            "\n提示：确认确为死代码后删除；删除前务必确认其依赖方也不在死代码集合内。\n"
            "误删活模块会打断 sidecar 的运行时状态机（如 backend/browser/worker_controller）。",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
