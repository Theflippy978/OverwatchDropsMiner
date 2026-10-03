"""pytest 全局配置与平台门禁。

两件事：

1. **平台门禁**
   CI 的 test job 跑在 `ubuntu-latest`，而 `test_dpapi.py` / `test_accounts.py`
   在**导入期**就 `ctypes.WinDLL`（非 Windows 上 AttributeError，属硬失败，
   `importorskip` 挡不住）。build-windows job `needs: [prepare, test]`，
   因此这条链路会被永久阻断。

   这里在**收集前**把平台相关的用例挡掉，而不是让它们红。
   Windows runner 上照常全跑 —— 本项目的主要开发环境是 Windows。

   新增门禁条目时的判据：该文件是否在导入期就碰 Windows-only 能力。
   只要是，就放进 `_WINDOWS_ONLY_FILES`；否则别加，否则会掩盖真实失败。

2. **asyncio 配置**
   pytest-asyncio 装在 requirements.txt，但没有 `asyncio_mode` 配置时它
   处于严格模式：有人写 `async def test_*` 而忘了加 marker，会被静默跳过。
   设为 auto。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

IS_WINDOWS = sys.platform == "win32"

# 这些文件整体依赖 Windows-only 能力（DPAPI 的 ctypes.WinDLL），
# 在非 Windows 上于导入期就失败，无法用文件级标记挽救。
_WINDOWS_ONLY_FILES = (
    "test_dpapi.py",
    "test_accounts.py",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """非 Windows 上跳过平台相关用例（统一在这里收口，避免散落各处）"""
    if IS_WINDOWS:
        return
    skip_win = pytest.mark.skip(reason="Windows-only（依赖 DPAPI），当前平台不可运行")
    for item in items:
        if Path(str(item.fspath)).name in _WINDOWS_ONLY_FILES:
            item.add_marker(skip_win)