from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class UpdateCheckResult:
    latest_version: str
    release_url: str


def normalize_version(value: str) -> str:
    return value.strip().lower().lstrip("v")


def _version_tuple(value: str) -> tuple[int, ...] | str:
    """解析版本号为可比较的整数元组；无法按点分段解析时回退为原字符串维持旧语义。"""
    normalized = normalize_version(value)
    parts = normalized.split(".")
    segments: list[int] = []
    for part in parts:
        if not part.isdigit():
            # 含非数字段（如 dev/alpha）时无法数值比较，返回原字符串走字符串不等比较
            return normalized
        segments.append(int(part))
    return tuple(segments)


def _is_newer_version(latest: str, current: str) -> bool:
    """判断 latest 是否严格比 current 新；本地比远端新时不应提示更新。"""
    latest_key = _version_tuple(latest)
    current_key = _version_tuple(current)
    if isinstance(latest_key, tuple) and isinstance(current_key, tuple):
        return latest_key > current_key
    # 任一侧解析失败时，退化为字符串不等比较以保持旧行为
    return latest_key != current_key


def should_check_update(
    app_version: str, update_channel: str, *, force: bool = False
) -> bool:
    """是否应该发起更新检查。

    ``force`` 只跳过 update_channel 这道门禁，**不**跳过版本号本身的校验：
    手动点「检查更新」时必须真的去查远端（否则本地包里这个按钮是死的），
    但形如 ``dev-abcdef`` / ``0.0.0+dev`` 的开发版版本号在任何模式下都不参与
    比较 —— 拿它去比远端 release 只会得到「有新版」这种无意义的结论。
    """
    if not force and update_channel != "release":
        return False
    current_version = normalize_version(app_version)
    # 用包含判断：形如 "0.0.0+dev" 的版本串 normalize 后不以 dev 开头，startswith 会失效
    return bool(current_version) and "dev" not in current_version


def parse_update_payload(
    payload: dict[str, Any],
    *,
    current_version: str,
    releases_url: str,
) -> UpdateCheckResult | None:
    latest_version = str(payload.get("tag_name") or "").strip()
    if not latest_version:
        return None
    if not _is_newer_version(latest_version, current_version):
        return None
    release_url = str(payload.get("html_url") or "").strip() or releases_url
    return UpdateCheckResult(latest_version=latest_version, release_url=release_url)


def check_latest_release(
    *,
    app_version: str,
    update_channel: str,
    latest_release_api: str,
    releases_url: str,
    timeout: float = 8,
    force: bool = False,
) -> UpdateCheckResult | None:
    if not should_check_update(app_version, update_channel, force=force):
        return None

    try:
        request = urllib.request.Request(
            latest_release_api,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "OverwatchDropsMiner",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # urlopen 对 HTTP>=400 直接抛 HTTPError，此处只需全量读取响应体
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return None
        return parse_update_payload(
            payload,
            current_version=app_version,
            releases_url=releases_url,
        )
    except Exception:
        return None

