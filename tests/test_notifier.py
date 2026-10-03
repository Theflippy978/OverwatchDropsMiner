from __future__ import annotations

import unittest
from unittest import mock

import httpx

from python_sidecar.backend.notifier import (
    MultiPlatformNotifier,
    _NativeNotifyTarget,
)


def _fake_response(status_code: int = 200, payload=None) -> httpx.Response:
    if payload is None:
        return httpx.Response(status_code)
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://unit.test/hook"),
    )


class FromUrlDispatchTest(unittest.TestCase):
    """T-1 盲区补充：from_url 的 scheme 分派与 webhook 识别。"""

    def test_native_schemes_are_recognized(self) -> None:
        for scheme in ("gotify", "gotifys", "schan", "wecombot", "wxwork"):
            with self.subTest(scheme=scheme):
                self.assertIsNotNone(
                    _NativeNotifyTarget.from_url(f"{scheme}://host/token")
                )

    def test_wecombot_webhook_requires_key(self) -> None:
        self.assertIsNone(
            _NativeNotifyTarget.from_url(
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
            )
        )
        self.assertIsNotNone(
            _NativeNotifyTarget.from_url(
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k"
            )
        )

    def test_unknown_scheme_returns_none_for_apprise(self) -> None:
        self.assertIsNone(
            _NativeNotifyTarget.from_url("smtp://user:pass@example.invalid")
        )


class GotifyTest(unittest.TestCase):
    def test_gotifys_prefix_token_and_priority(self) -> None:
        target = _NativeNotifyTarget.from_url(
            "gotifys://push.example.invalid/parent/TOKEN?priority=8"
        )
        assert target is not None
        with mock.patch(
            "python_sidecar.backend.notifier.httpx.post",
            return_value=_fake_response(200),
        ) as post:
            self.assertTrue(target.notify("标题", "内容"))
        endpoint = post.call_args.args[0]
        headers = post.call_args.kwargs["headers"]
        body = post.call_args.kwargs["json"]
        self.assertEqual(endpoint, "https://push.example.invalid/parent/message")
        self.assertEqual(headers["X-Gotify-Key"], "TOKEN")
        self.assertEqual(body["priority"], 8)

    def test_gotify_default_priority(self) -> None:
        target = _NativeNotifyTarget.from_url("gotify://host/TOKEN")
        assert target is not None
        with mock.patch(
            "python_sidecar.backend.notifier.httpx.post",
            return_value=_fake_response(200),
        ) as post:
            self.assertTrue(target.notify("t", "b"))
        self.assertEqual(post.call_args.kwargs["json"]["priority"], 5)

    def test_gotify_missing_token_raises(self) -> None:
        # notify() 会把构造期校验异常吞掉转为 False；直接对内部方法断言
        target = _NativeNotifyTarget.from_url("gotify://host")
        assert target is not None
        with self.assertRaises(ValueError):
            target._notify_gotify("t", "b")


class ServerChanTest(unittest.TestCase):
    def test_title_truncated_to_32_chars(self) -> None:
        target = _NativeNotifyTarget.from_url("schan://SCT_TOKEN")
        assert target is not None
        long_title = "标" * 40
        with mock.patch(
            "python_sidecar.backend.notifier.httpx.post",
            return_value=_fake_response(200, {"code": 0}),
        ) as post:
            self.assertTrue(target.notify(long_title, "body"))
        url = post.call_args.args[0]
        data = post.call_args.kwargs["data"]
        self.assertEqual(url, "https://sctapi.ftqq.com/SCT_TOKEN.send")
        self.assertEqual(len(data["title"]), 32)


class WecombotTest(unittest.TestCase):
    def test_query_key_not_double_decoded(self) -> None:
        # %2B 即 '+'：query 已被 parse_qs 解码一次，二次 unquote 会把
        # '+' 变空格破坏 key（回归点，见 notifier.py 注释）
        target = _NativeNotifyTarget.from_url(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc%2Bdef"
        )
        assert target is not None
        with mock.patch(
            "python_sidecar.backend.notifier.httpx.post",
            return_value=_fake_response(200, {"errcode": 0}),
        ) as post:
            self.assertTrue(target.notify("t", "b"))
        url = str(post.call_args.args[0])
        # parse_qs 已解码一次（%2B -> '+'），实现不得再 unquote；
        # httpx 对 query 中的 '+' 原样发送，服务端按其自身口径解码。
        self.assertIn("key=abc+def", url)


class SuccessPayloadNormalizationTest(unittest.TestCase):
    """_is_success_response 的 errcode/code 归一化口径（T-1）。"""

    def _target(self) -> _NativeNotifyTarget:
        target = _NativeNotifyTarget.from_url("gotify://host/TOKEN")
        assert target is not None
        return target

    def test_payload_variants(self) -> None:
        cases = [
            ({"errcode": 0}, True),
            ({"errcode": "0"}, True),
            ({"errcode": 0.0}, True),
            ({"code": 0}, True),
            ({"errcode": None, "code": 1}, False),
            ({"errcode": None, "code": None}, True),
            ({}, True),
            ({"errcode": 1}, False),
            ({"errcode": "oops"}, False),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                target = self._target()
                with mock.patch(
                    "python_sidecar.backend.notifier.httpx.post",
                    return_value=_fake_response(200, payload),
                ):
                    self.assertEqual(target.notify("t", "b"), expected)

    def test_http_error_status_fails(self) -> None:
        target = self._target()
        with mock.patch(
            "python_sidecar.backend.notifier.httpx.post",
            return_value=_fake_response(500),
        ):
            self.assertFalse(target.notify("t", "b"))


class WxworkTokenCacheTest(unittest.TestCase):
    """wxwork access_token 缓存行为（T-1）与失效自愈（D-3 回归）。"""

    def _target(self) -> _NativeNotifyTarget:
        target = _NativeNotifyTarget.from_url("wxwork://CORP/1000002/SECRET?to=userA")
        assert target is not None
        return target

    @staticmethod
    def _install(responses: list[httpx.Response], tokens: list[str]):
        gettoken_calls = {"count": 0}

        def fake_post(
            url=None, params=None, json=None, timeout=None, **kwargs
        ):
            assert params is not None and "access_token" in params
            return responses.pop(0)

        def fake_get(url=None, params=None, timeout=None, **kwargs):
            gettoken_calls["count"] += 1
            token = tokens.pop(0)
            return _fake_response(200, {"errcode": 0, "access_token": token})

        return (
            mock.patch("python_sidecar.backend.notifier.httpx.post", side_effect=fake_post),
            mock.patch("python_sidecar.backend.notifier.httpx.get", side_effect=fake_get),
            gettoken_calls,
        )

    def test_token_reused_within_cache_window(self) -> None:
        target = self._target()
        post_patch, get_patch, calls = self._install(
            [
                _fake_response(200, {"errcode": 0}),
                _fake_response(200, {"errcode": 0}),
            ],
            ["TOKEN_A"],
        )
        with post_patch as post, get_patch as get:
            self.assertTrue(target.notify("t1", "b"))
            self.assertTrue(target.notify("t2", "b"))
        self.assertEqual(get.call_count, 1)
        self.assertEqual(post.call_count, 2)

    def test_expired_token_cleared_and_message_retried(self) -> None:
        target = self._target()
        post_patch, get_patch, calls = self._install(
            [
                _fake_response(200, {"errcode": 40014, "errmsg": "invalid"}),
                _fake_response(200, {"errcode": 0}),
            ],
            ["TOKEN_OLD", "TOKEN_NEW"],
        )
        with post_patch as post, get_patch as get:
            self.assertTrue(target.notify("t", "b"))
        self.assertEqual(get.call_count, 2)
        self.assertEqual(post.call_count, 2)
        retry_params = post.call_args_list[-1].kwargs.get("params") or {}
        self.assertEqual(retry_params.get("access_token"), "TOKEN_NEW")


class UpdateUrlsBehaviorTest(unittest.TestCase):
    """D-4 回归：坏 URL 不连累其它目标；enabled 口径正确。"""

    def test_bad_url_does_not_break_native_targets(self) -> None:
        notifier = MultiPlatformNotifier(
            ["gotify://host/TOKEN", "not-a-valid-scheme://whatever"]
        )
        self.assertTrue(notifier.enabled)
        self.assertEqual(len(notifier._native_targets), 1)

    def test_only_bad_urls_disables_notifier(self) -> None:
        notifier = MultiPlatformNotifier(["not-a-valid-scheme://whatever"])
        self.assertFalse(notifier.enabled)


if __name__ == "__main__":
    unittest.main()
