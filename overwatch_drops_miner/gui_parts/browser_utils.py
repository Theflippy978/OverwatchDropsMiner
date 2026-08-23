from __future__ import annotations

import os
import re


def find_browser_binary(name: str) -> str | None:
    """Return the browser executable used by Selenium on this platform."""
    if name == "edge":
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    else:
        paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
            ),
        ]
    return next((path for path in paths if os.path.exists(path)), None)


def find_browser(name: str) -> bool:
    return find_browser_binary(name) is not None


def detect_default_browser() -> str | None:
    progids: list[str] = []
    try:
        import winreg

        for scheme in ("https", "http"):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    rf"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{scheme}\UserChoice",
                ) as key:
                    progids.append(winreg.QueryValueEx(key, "ProgId")[0].lower())
            except OSError:
                continue
    except Exception:
        progids = []

    for progid in progids:
        if "chrome" in progid and "edge" not in progid:
            return "chrome"
        if "edge" in progid or "msedge" in progid:
            return "edge"
    return None


def available_browsers() -> list[str]:
    return [browser for browser in ("chrome", "edge") if find_browser(browser)]


def browser_label(browser: str) -> str:
    return {"chrome": "Google Chrome", "edge": "Microsoft Edge"}.get(
        browser, browser
    )


def browser_try_order(preferred: str | None) -> tuple[str, ...]:
    available = available_browsers()
    if not available:
        return ()
    if preferred and preferred in available:
        return (preferred, *[item for item in available if item != preferred])
    default = detect_default_browser()
    if default in available:
        return (default, *[item for item in available if item != default])
    return tuple(available)


def extract_room_id_from_live_url(text: str) -> int | None:
    if not text:
        return None
    for pattern in (
        r"https?://live\.bilibili\.com/blanc/(\d+)",
        r"https?://live\.bilibili\.com/(\d+)",
        r"live\.bilibili\.com/blanc/(\d+)",
        r"live\.bilibili\.com/(\d+)",
    ):
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            room_id = int(match.group(1))
        except Exception:
            continue
        if room_id > 0:
            return room_id
    return None
