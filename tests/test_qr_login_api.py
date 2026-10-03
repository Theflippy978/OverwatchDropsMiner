"""扫码登录 API 层测试（跨平台可跑）。

2026-10-02 从 test_qr_login.py 拆出：该文件顶层 `from PySide6.QtWidgets import
...` 在 Linux（PySide6-Essentials 无 QtWidgets）于**收集期**就 ImportError，
导致这里这 10 个纯逻辑用例一起收集失败，而 QrLoginApiTests 测的其实是
**活代码** client_parts/qr_login.py（Tauri 运行时不依赖 Qt）。

拆分后本文件无 Qt 依赖，可在所有平台运行；Qt 相关的对话框测试留在
test_qr_login.py，由 tests/conftest.py 在非 Windows 上跳过。
"""
from __future__ import annotations

import http.cookiejar
import unittest
import unittest.mock


import httpx


from python_sidecar.backend.client_parts.qr_login import (
    QrLoginApi,
    QrLoginError,
    QrLoginStatus,
    build_login_cookie_string,
    parse_generate_payload,
    parse_poll_payload,
)


class QrLoginApiTests(unittest.TestCase):
    def test_generate_payload_requires_success_and_expected_fields(self) -> None:
        challenge = parse_generate_payload(
            {
                "code": 0,
                "data": {
                    "url": "https://passport.example.invalid/qr",
                    "qrcode_key": "temporary-key",
                },
            }
        )
        self.assertEqual(challenge.key, "temporary-key")

        invalid_payloads = (
            {"code": -1, "data": {}},
            {"code": False, "data": {}},
            {"code": 0, "data": None},
            {"code": 0, "data": {"url": "http://insecure.invalid", "qrcode_key": "k"}},
            {"code": 0, "data": {"url": "https://example.invalid", "qrcode_key": ""}},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(QrLoginError):
                parse_generate_payload(payload)

    def test_poll_payload_maps_all_documented_states_and_rejects_unknown(self) -> None:
        expected = {
            86101: QrLoginStatus.UNSCANNED,
            86090: QrLoginStatus.CONFIRMED_PENDING,
            86038: QrLoginStatus.EXPIRED,
            0: QrLoginStatus.SUCCESS,
        }
        for code, status in expected.items():
            with self.subTest(code=code):
                self.assertIs(
                    parse_poll_payload({"code": 0, "data": {"code": code}}),
                    status,
                )

        with self.assertRaisesRegex(QrLoginError, "未知扫码状态码"):
            parse_poll_payload({"code": 0, "data": {"code": 12345}})
        with self.assertRaises(QrLoginError):
            parse_poll_payload({"code": 0, "data": {"code": "0"}})

    def test_cookie_filter_uses_safe_names_and_requires_three_login_items(self) -> None:
        client_cookies = httpx.Cookies()
        client_cookies.set("buvid3", "device", domain=".bilibili.com")
        response_cookies = httpx.Cookies()
        response_cookies.set("SESSDATA", "session", domain=".bilibili.com")
        response_cookies.set("DedeUserID", "42", domain=".bilibili.com")
        response_cookies.set("bili_jct", "csrf", domain=".bilibili.com")
        response_cookies.set("refresh_token", "must-not-be-saved", domain=".bilibili.com")

        cookie = build_login_cookie_string(response_cookies, client_cookies)

        self.assertEqual(
            cookie,
            "SESSDATA=session; bili_jct=csrf; DedeUserID=42; buvid3=device",
        )
        self.assertNotIn("refresh_token", cookie)

        response_cookies.delete("bili_jct", domain=".bilibili.com")
        with self.assertRaisesRegex(QrLoginError, "Cookie 不完整"):
            build_login_cookie_string(response_cookies, client_cookies)

    def test_cookie_filter_excludes_foreign_domain_and_expired_cookies(self) -> None:
        # 异域同名 Cookie 放在先遍历的 client jar 中，验证其被域名过滤、
        # 且不会覆盖 response jar 中的合法登录态
        client_cookies = httpx.Cookies()
        client_cookies.set("buvid3", "device", domain=".bilibili.com")
        client_cookies.set("bili_jct", "evil-value", domain=".example.com")

        response_cookies = httpx.Cookies()
        response_cookies.set("SESSDATA", "session", domain=".bilibili.com")
        response_cookies.set(
            "DedeUserID", "42", domain=".bilibili.com"
        )
        response_cookies.set("bili_jct", "csrf", domain=".bilibili.com")
        # 已过期的 Cookie 应被忽略
        expired = http.cookiejar.Cookie(
            version=0,
            name="sid",
            value="stale",
            port=None,
            port_specified=False,
            domain=".bilibili.com",
            domain_specified=True,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=False,
            expires=1000000000,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        response_cookies.jar.set_cookie(expired)

        cookie = build_login_cookie_string(response_cookies, client_cookies)

        self.assertIn("SESSDATA=session", cookie)
        self.assertNotIn("evil-value", cookie)
        self.assertNotIn("stale", cookie)

    def test_poll_retries_once_on_transient_connect_error(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if request.url.path.endswith("/generate"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "url": "https://passport.example.invalid/qr",
                            "qrcode_key": "temporary-key",
                        },
                    },
                )
            if attempts["n"] == 2:
                # 第一次轮询抛瞬时连接异常，应触发一次重试
                raise httpx.ConnectError("boom")
            return httpx.Response(
                200, json={"code": 0, "data": {"code": 86101}}
            )

        client = httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"Referer": "https://passport.bilibili.com/login"},
        )
        api = QrLoginApi(client)
        try:
            with unittest.mock.patch(
                "python_sidecar.backend.client_parts.qr_login.time.sleep"
            ) as sleep_mock:
                challenge = api.generate()
                result = api.poll(challenge.key)
        finally:
            api.close()

        self.assertEqual(attempts["n"], 3)
        self.assertIs(result.status, QrLoginStatus.UNSCANNED)
        sleep_mock.assert_called_once()

    def test_api_reuses_client_and_collects_success_response_cookies(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path.endswith("/generate"):
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "url": "https://passport.example.invalid/qr",
                            "qrcode_key": "temporary-key",
                        },
                    },
                )
            return httpx.Response(
                200,
                json={"code": 0, "data": {"code": 0}},
                headers=[
                    ("set-cookie", "SESSDATA=session; Domain=.bilibili.com; Path=/"),
                    ("set-cookie", "DedeUserID=42; Domain=.bilibili.com; Path=/"),
                    ("set-cookie", "bili_jct=csrf; Domain=.bilibili.com; Path=/"),
                    ("set-cookie", "refresh_token=ignored; Domain=.bilibili.com; Path=/"),
                ],
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        api = QrLoginApi(client)
        try:
            challenge = api.generate()
            result = api.poll(challenge.key)
        finally:
            api.close()

        self.assertIs(result.status, QrLoginStatus.SUCCESS)
        self.assertEqual(
            result.cookie,
            "SESSDATA=session; bili_jct=csrf; DedeUserID=42",
        )
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].url.params["qrcode_key"], "temporary-key")
