from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# 检查结果的四种状态。**它们必须互相可区分** —— 历史上这里只有一个
# 「有没有新版」的布尔值，于是下面这些完全不同的情况在界面上都显示成
# 「已是最新版本」，用户和开发者都无从察觉：
#
#   * GitHub 未认证接口限流（HTTP 403，60 次/小时）
#   * 网络不可达 / DNS 失败 / 请求超时
#   * 远端返回的不是 JSON、或结构不符合预期
#   * 本地版本号是 `0.0.0+dev` 这类占位串，压根没发请求
#
# 前三种是「没查成」，第四种是「不该查」，只有真正比对完成且不落后
# 才是「已是最新」。把「没查成」说成「已是最新」等于向用户撒谎。
STATUS_UP_TO_DATE = "up_to_date"
STATUS_UPDATE_AVAILABLE = "update_available"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

# 自动检查的最小间隔。GitHub 未认证接口只有 60 次/小时，而「每次启动查一次」
# 在爱重启的用户手里几十次就耗尽了 —— 耗尽后所有检查都会失败（修复前还会
# 谎称「已是最新」）。每天一次足够：本项目的发布节奏以天计，而手动按钮
# 随时可用、不受这个间隔约束。
AUTO_CHECK_MIN_INTERVAL_SECONDS = 24 * 60 * 60


@dataclass(slots=True)
class UpdateCheckResult:
    latest_version: str
    release_url: str


@dataclass(slots=True)
class UpdateCheckOutcome:
    """一次更新检查的完整结论：状态 + 可选的新版信息 + 面向用户的说明。"""

    status: str
    result: UpdateCheckResult | None = None
    message: str = ""
    # 是否**真的向 GitHub 发过请求**。调用方据此决定要不要记「上次检查时间」：
    # 被渠道门禁或占位版本号拦下的 skipped 根本没打扰远端，不该占用当天额度。
    requested: bool = False

    @property
    def update_available(self) -> bool:
        return self.status == STATUS_UPDATE_AVAILABLE


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


def is_comparable_version(value: str) -> bool:
    """版本号是否可用于「有没有新版」的数值比较。

    判定标准是**能不能解析成纯数字点分**，而不是「里面有没有 dev 字样」：
    后者把「渠道」与「版本号」两件事混在一起 —— ``dev`` 渠道的版本号
    （如 ``1.1.0``）本来是完全可以比较的，却会被误判成不可比较，
    导致手动检查也直接返回、按钮变空操作。

    不可比较的例子：``dev-abcdef``（含短 SHA）、``0.0.0+dev``（含本地段）。
    这类值拿去比远端 tag 只会得到「有新版」这种无意义结论，故仍应拒绝。
    """
    normalized = normalize_version(value)
    if not normalized:
        return False
    return all(part.isdigit() for part in normalized.split("."))


def should_check_update(
    app_version: str, update_channel: str, *, force: bool = False
) -> bool:
    """是否应该发起更新检查。

    ``force``（手动点「检查更新」）**只**跳过 ``update_channel`` 这道门禁，
    不跳过版本号可比较性校验：渠道是「要不要打扰 GitHub」的策略问题，
    而版本号能不能比较是「这个判断有没有意义」的正确性问题。

    两者分开之后，dev 渠道 + 真实版本号（``1.1.0``）手动检查会真的发请求；
    而 ``dev-abcdef`` 这类占位版本号无论手动还是自动都不查 —— 那才是
    真正无意义的比较。
    """
    if not force and update_channel != "release":
        return False
    return is_comparable_version(app_version)


def skip_reason(app_version: str, update_channel: str, *, force: bool) -> str:
    """不发起检查的原因，直接给用户看。

    调用方只在 ``should_check_update`` 为假时用它。返回空串表示「其实该查」，
    那说明调用方判错了，不是本函数的事。
    """
    if not force and update_channel != "release":
        return f"当前是 {update_channel} 渠道，未开启自动检查"
    if not is_comparable_version(app_version):
        shown = app_version.strip() or "(空)"
        return f"当前版本号 {shown} 不是可比较的发布版本号，无法检查更新"
    return ""


def should_auto_check_now(
    last_checked_at: float | None,
    *,
    now: float,
    min_interval: float = AUTO_CHECK_MIN_INTERVAL_SECONDS,
) -> bool:
    """自动检查是否到了该跑的时候。

    **手动点按钮不走这个判断** —— 用户主动要看结果时不该被节流拦住。

    时钟被往回调过（``now < last_checked_at``）时放行并按新时间重记：
    否则一次误调系统时间就会把自动检查锁死到「未来某天」之后。
    """
    if last_checked_at is None:
        return True
    if now < last_checked_at:
        return True
    return (now - last_checked_at) >= min_interval


def parse_state(raw: str) -> float | None:
    """从状态文件内容里取出上次检查时间。

    任何坏数据（空文件、被截断、字段类型不对）都当作「从没检查过」——
    宁可多查一次，也不要因为一个坏文件把自动检查永久卡住。
    """
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("last_checked_at")
    # bool 是 int 的子类，必须先排掉，否则 True 会被当成时间戳 1.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def dump_state(when: float) -> str:
    return json.dumps({"last_checked_at": when}, ensure_ascii=False)


def parse_update_payload(
    payload: dict[str, Any],
    *,
    current_version: str,
    releases_url: str,
) -> UpdateCheckOutcome:
    latest_version = str(payload.get("tag_name") or "").strip()
    if not latest_version:
        # 与「已是最新」区分开：这是远端数据有问题，不是我们没落后
        return UpdateCheckOutcome(
            STATUS_FAILED, message="远端返回里没有版本号，无法判断是否有新版"
        )
    if not _is_newer_version(latest_version, current_version):
        return UpdateCheckOutcome(STATUS_UP_TO_DATE)
    release_url = str(payload.get("html_url") or "").strip() or releases_url
    return UpdateCheckOutcome(
        STATUS_UPDATE_AVAILABLE,
        result=UpdateCheckResult(latest_version=latest_version, release_url=release_url),
    )


def check_latest_release(
    *,
    app_version: str,
    update_channel: str,
    latest_release_api: str,
    releases_url: str,
    timeout: float = 8,
    force: bool = False,
) -> UpdateCheckOutcome:
    """查一次远端最新 release，**永不抛异常**，一切情况都体现在 status 上。

    两道门禁彼此独立，各管一件事：
    * ``should_check_update`` —— **该不该查**（渠道 + 版本号可比较性），在这里；
    * ``should_auto_check_now`` —— **自动检查今天查过没有**，由调用方在进入本函数
      之前判断（手动点按钮不走它）。

    失败信息只用固定文案与异常类型名，**不回显远端内容**：``URLError.reason``
    之类的字符串来自网络层，直接塞进界面等于让远端决定我们显示什么。
    """
    if not should_check_update(app_version, update_channel, force=force):
        return UpdateCheckOutcome(
            STATUS_SKIPPED,
            message=skip_reason(app_version, update_channel, force=force),
        )

    outcome = _request_latest_release(
        app_version=app_version,
        latest_release_api=latest_release_api,
        releases_url=releases_url,
        timeout=timeout,
    )
    # 走到这里说明**真的打扰了 GitHub** —— 无论成败都算「查过一次」。
    # 失败也记时间是有意的：限流时越试越糟，而手动按钮随时可用。
    outcome.requested = True
    return outcome


def _request_latest_release(
    *,
    app_version: str,
    latest_release_api: str,
    releases_url: str,
    timeout: float,
) -> UpdateCheckOutcome:
    """真正发请求的那一半，只被 ``check_latest_release`` 调用。"""
    request = urllib.request.Request(
        latest_release_api,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OverwatchDropsMiner",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # urlopen 对 HTTP>=400 直接抛 HTTPError，此处只需全量读取响应体
            raw = response.read()
    except urllib.error.HTTPError as exc:
        # HTTPError 是 URLError 的子类，必须先捕获它，否则 403 会被当成普通网络错误。
        # 文案里保留状态码：它是排障时唯一能区分「限流 / 仓库没发布 / 服务端故障」
        # 的线索，去掉就只能靠猜。
        if exc.code == 403:
            message = (
                "GitHub 拒绝了这次请求（HTTP 403，未认证接口限流 60 次/小时），"
                "请稍后重试"
            )
        elif exc.code == 404:
            message = "远端仓库还没有发布任何版本（HTTP 404）"
        else:
            message = f"GitHub 返回 HTTP {exc.code}"
        return UpdateCheckOutcome(STATUS_FAILED, message=message)
    except TimeoutError:
        return UpdateCheckOutcome(
            STATUS_FAILED, message=f"请求超时（超过 {timeout:.0f} 秒）"
        )
    except urllib.error.URLError:
        return UpdateCheckOutcome(STATUS_FAILED, message="网络不可达，请检查网络连接")
    except Exception as exc:  # noqa: BLE001 —— 兜底：这条路径绝不能把异常抛给调用方
        return UpdateCheckOutcome(
            STATUS_FAILED, message=f"请求失败（{type(exc).__name__}）"
        )

    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return UpdateCheckOutcome(STATUS_FAILED, message="远端返回的不是合法 JSON")

    if not isinstance(payload, dict):
        return UpdateCheckOutcome(STATUS_FAILED, message="远端返回的结构不符合预期")

    return parse_update_payload(
        payload,
        current_version=app_version,
        releases_url=releases_url,
    )
