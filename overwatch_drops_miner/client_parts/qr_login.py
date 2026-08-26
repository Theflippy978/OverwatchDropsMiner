from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

import httpx


QR_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

LOGIN_COOKIE_NAMES = (
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "buvid3",
    "b_nut",
    "sid",
)
REQUIRED_LOGIN_COOKIE_NAMES = ("SESSDATA", "DedeUserID", "bili_jct")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": "https://passport.bilibili.com/login",
    "Accept": "application/json, text/plain, */*",
}


class QrLoginError(RuntimeError):
    """A safe-to-display QR login failure that never contains credentials."""


class QrLoginStatus(Enum):
    UNSCANNED = 86101
    CONFIRMED_PENDING = 86090
    EXPIRED = 86038
    SUCCESS = 0


@dataclass(frozen=True, slots=True)
class QrLoginChallenge:
    url: str
    key: str


@dataclass(frozen=True, slots=True)
class QrPollResult:
    status: QrLoginStatus
    cookie: str = ""


def _payload_data(payload: Any, operation: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise QrLoginError(f"{operation}响应格式无效")
    outer_code = payload.get("code")
    if isinstance(outer_code, bool) or not isinstance(outer_code, int):
        raise QrLoginError(f"{operation}响应缺少有效状态码")
    if outer_code != 0:
        raise QrLoginError(f"{operation}失败（接口状态异常）")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise QrLoginError(f"{operation}响应缺少 data")
    return data


def parse_generate_payload(payload: Any) -> QrLoginChallenge:
    data = _payload_data(payload, "生成二维码")
    url = data.get("url")
    key = data.get("qrcode_key")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise QrLoginError("生成二维码响应缺少有效地址")
    if not isinstance(key, str) or not key.strip():
        raise QrLoginError("生成二维码响应缺少有效标识")
    return QrLoginChallenge(url=url, key=key)


def parse_poll_payload(payload: Any) -> QrLoginStatus:
    data = _payload_data(payload, "查询扫码状态")
    code = data.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        raise QrLoginError("查询扫码状态响应缺少有效状态码")
    try:
        return QrLoginStatus(code)
    except ValueError as exc:
        raise QrLoginError(f"未知扫码状态码：{code}") from exc


def build_login_cookie_string(
    response_cookies: httpx.Cookies,
    client_cookies: httpx.Cookies,
) -> str:
    """Select the safe login cookies obtained by the successful poll request."""

    selected: dict[str, str] = {}
    # The client jar contains cookies accepted from this session, while the
    # response jar lets the successful poll response take precedence.
    for cookie_jar in (client_cookies.jar, response_cookies.jar):
        for cookie in cookie_jar:
            if cookie.name not in LOGIN_COOKIE_NAMES or not cookie.value:
                continue
            # 仅取 B 站主域的未过期 Cookie，避免同名异域/过期项污染登录态；
            # 精确匹配主域或其子域，防止 xbilibili.com 类同形后缀域（J-3）
            domain = (cookie.domain or "").lstrip(".")
            if domain != "bilibili.com" and not domain.endswith(".bilibili.com"):
                continue
            if cookie.is_expired():
                continue
            selected[cookie.name] = cookie.value

    missing = [name for name in REQUIRED_LOGIN_COOKIE_NAMES if not selected.get(name)]
    if missing:
        raise QrLoginError("扫码成功，但登录 Cookie 不完整，请重新扫码")
    return "; ".join(
        f"{name}={selected[name]}" for name in LOGIN_COOKIE_NAMES if name in selected
    )


class QrLoginApi:
    """One Bilibili QR login session backed by one HTTP client/cookie jar."""

    # 与 client_parts/http.py 的 GET 瞬时异常口径一致（J-4）：扫码
    # 「确认中」轮询遇读超时不应终止整轮登录。
    _TRANSIENT_ERRORS = (
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    )

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(
            headers=_HEADERS,
            timeout=httpx.Timeout(10.0, connect=10.0),
            follow_redirects=False,
        )

    def _get_once(self, url: str, **kwargs: Any) -> httpx.Response:
        # 扫码轮询链路无瞬时重试保护，一次网络抖动就会让整轮扫码流程失败，
        # 这里对连接类瞬时异常做一次轻量重试。
        try:
            return self._client.get(url, **kwargs)
        except self._TRANSIENT_ERRORS:
            time.sleep(0.5)
        return self._client.get(url, **kwargs)

    def generate(self) -> QrLoginChallenge:
        response = self._get_once(QR_GENERATE_URL)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise QrLoginError("生成二维码响应不是有效 JSON") from exc
        return parse_generate_payload(payload)

    def poll(self, key: str) -> QrPollResult:
        response = self._get_once(QR_POLL_URL, params={"qrcode_key": key})
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise QrLoginError("查询扫码状态响应不是有效 JSON") from exc
        status = parse_poll_payload(payload)
        if status is not QrLoginStatus.SUCCESS:
            return QrPollResult(status=status)
        cookie = build_login_cookie_string(response.cookies, self._client.cookies)
        return QrPollResult(status=status, cookie=cookie)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> QrLoginApi:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
