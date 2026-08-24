from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found, installing...")
        # 锁定最低版本，保证构建行为可重现
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"]
        )


def format_cmd(cmd: list[str]) -> str:
    return subprocess.list2cmdline(cmd)


def build(
    entry: str,
    name: str,
    *,
    clean: bool = False,
    debug: bool = False,
    extra_args: Iterable[str] | None = None,
) -> None:
    # 资源路径基于脚本所在目录解析，避免从其它工作目录运行 build.py 时找不到图标
    project_root = Path(__file__).resolve().parent
    icon_path = project_root / "img" / "app.ico"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--name",
        name,
        "--onefile",
        "--windowed",
        "--noupx",
        "--clean" if clean else None,
        "--icon",
        str(icon_path),
        "--add-data",
        f"{icon_path};img",
    ]
    cmd = [part for part in cmd if part]

    if debug:
        cmd.extend(["--log-level", "DEBUG"])

    if extra_args:
        cmd.extend(extra_args)

    cmd.append(entry)

    print(f"\nBuilding {name}.exe ...")
    print(format_cmd(cmd))
    subprocess.check_call(cmd)
    print(f"Done: dist/{name}.exe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build OverwatchDropsMiner with PyInstaller (Windows onefile)."
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="clean PyInstaller cache before build.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable PyInstaller debug log output.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ensure_pyinstaller()

    # 发布包使用 notifier.py 里的轻量内置通知，避免把 Apprise 的全量插件
    # 都塞进包里；同时排除大量与 GUI 无关的可选依赖以压缩体积。
    excluded_modules = (
        "IPython",
        "jedi",
        "jinja2",
        "matplotlib",
        "numpy",
        "PIL",
        "prompt_toolkit",
        "pygments",
        "tkinter",
        "traitlets",
        "apprise",
        "colorama",
        "pytest",
        "setuptools",
        "pip",
    )
    exclude_args: list[str] = []
    for module_name in excluded_modules:
        exclude_args.extend(["--exclude-module", module_name])

    gui_extra_args = exclude_args + [
        "--collect-all",
        "selenium",
    ]

    build(
        "main.py",
        "OverwatchDropsMiner",
        clean=args.clean,
        debug=args.debug,
        extra_args=gui_extra_args,
    )
    print("\nBuild complete. Output: dist/OverwatchDropsMiner.exe")


if __name__ == "__main__":
    main()
