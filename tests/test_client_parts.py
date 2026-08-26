from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
import unittest.mock
import urllib.parse

import httpx

from overwatch_drops_miner.client_parts import core as core_module
from overwatch_drops_miner.client_parts.constants import WBI_MIXIN_KEY_ENC_TAB
from overwatch_drops_miner.client_parts.cookies import (
    DEFAULT_USER_AGENT,
    build_cookie_state,
    build_live_headers,
    build_mission_headers,
)
from overwatch_drops_miner.client_parts.models import (
    MissionRewardInfo,
    TaskCheckpointProgress,
    TaskProgress,
)
from overwatch_drops_miner.client_parts.profile import (
    parse_self_info,
    validate_nav_payload,
)
from overwatch_drops_miner.client_parts.task_parsing import (
    coerce_task_number,
    extract_task_indicator_values,
)
from overwatch_drops_miner.client_parts.task_discovery import fetch_live_task_groups
from overwatch_drops_miner.client_parts.wbi import (
    encode_query,
    parse_wbi_keys_from_nav,
    sign_wbi_params,
)


class ClientPartsTest(unittest.TestCase):
    def test_fetch_live_task_groups_follows_redirect_and_sets_headers(self) -> None:
        requests: list[httpx.Request] = []
        state = {
            "EraTasklistPc": [{"tasklist": [{"taskId": "task-a"}]}],
            "EvaPositionBox": [{"left": 0, "top": 0}],
            "EvaTabs.Panel": [
                {
                    "id": "today",
                    "tabItem": {"tabItemProps": {"textContent": {"content": "今天"}}},
                }
            ],
            "EvaTabs": [{"activatedTabPanelId": "today"}],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/23612045":
                return httpx.Response(302, headers={"Location": "/redirected"})
            return httpx.Response(
                200,
                text=f"<script>window.__initialState = {json.dumps(state)};</script>",
            )

        groups = fetch_live_task_groups(
            23612045,
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(
            [request.url.path for request in requests],
            ["/23612045", "/redirected"],
        )
        self.assertEqual(requests[0].headers["User-Agent"], DEFAULT_USER_AGENT)
        self.assertEqual(requests[0].headers["Referer"], "https://live.bilibili.com/")
        self.assertEqual(groups[0]["task_ids"], ["task-a"])

    def test_fetch_live_task_groups_returns_empty_static_result(self) -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, text="<html>no tasks</html>")
        )
        self.assertEqual(fetch_live_task_groups(1, transport=transport), [])

    def test_fetch_live_task_groups_raises_for_http_error(self) -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(503, text="upstream detail")
        )
        with self.assertRaises(httpx.HTTPStatusError):
            fetch_live_task_groups(1, transport=transport)

    def test_task_completion_and_reward_status(self) -> None:
        self.assertTrue(
            TaskProgress(
                task_id="task-a",
                task_name="watch",
                status=1,
                cur_value=60,
                limit_value=60,
            ).is_completed
        )
        self.assertFalse(
            TaskProgress(
                task_id="task-a",
                task_name="watch",
                status=1,
                cur_value=30,
                limit_value=60,
            ).is_completed
        )
        self.assertTrue(
            TaskProgress(
                task_id="task-a",
                task_name="watch",
                status=6,
                cur_value=0,
                limit_value=0,
            ).is_completed
        )

        claimable = MissionRewardInfo(
            task_id="task-a",
            task_name="watch",
            status=0,
            message="",
            act_id="act",
            act_name="activity",
            reward_name="reward",
        )
        claimed = MissionRewardInfo(
            task_id="task-a",
            task_name="watch",
            status=6,
            message="已领取",
            act_id="act",
            act_name="activity",
            reward_name="reward",
        )
        self.assertTrue(claimable.is_claimable)
        self.assertFalse(claimable.is_claimed)
        self.assertFalse(claimed.is_claimable)
        self.assertTrue(claimed.is_claimed)

    def test_is_completed_respects_terminal_status(self) -> None:
        # 服务器终态（status=3 已完成）优先于本地计数，cur 滞后也应视为完成
        self.assertTrue(
            TaskCheckpointProgress(
                sid="cp-a",
                alias="watch",
                status=3,
                cur_value=10,
                limit_value=60,
            ).is_completed
        )
        # 计数达标（cur>=limit）即使 status 仍为 0 也视为完成
        self.assertTrue(
            TaskCheckpointProgress(
                sid="cp-b",
                alias="watch",
                status=0,
                cur_value=60,
                limit_value=60,
            ).is_completed
        )
        self.assertFalse(
            TaskCheckpointProgress(
                sid="cp-c",
                alias="watch",
                status=0,
                cur_value=30,
                limit_value=60,
            ).is_completed
        )

    def test_task_indicator_parsing_prefers_watch_indicator(self) -> None:
        self.assertEqual(coerce_task_number("12"), 12)
        self.assertEqual(coerce_task_number("12.5"), 12.5)
        self.assertEqual(coerce_task_number("not-a-number"), 0)

        cur_value, limit_value = extract_task_indicator_values(
            [
                {"type": "coin", "cur_value": 9, "limit": 99},
                {"type": "watch_time", "cur_value": "30", "limit": "60"},
            ]
        )
        self.assertEqual((cur_value, limit_value), (30, 60))

    def test_wbi_key_parse_and_signature(self) -> None:
        img_key = "abcdefghijklmnopqrstuvwxyzabcdef"
        sub_key = "1234567890abcdef1234567890abcdef"
        payload = {
            "data": {
                "wbi_img": {
                    "img_url": f"https://i0.hdslb.com/bfs/wbi/{img_key}.png",
                    "sub_url": f"https://i0.hdslb.com/bfs/wbi/{sub_key}.png",
                }
            }
        }
        self.assertEqual(parse_wbi_keys_from_nav(payload), (img_key, sub_key))

        params = {"b": "2", "a": "x! y"}
        signed = sign_wbi_params(params, img_key=img_key, sub_key=sub_key, timestamp=123)

        raw_mixin = img_key + sub_key
        mixin_key = "".join(raw_mixin[index] for index in WBI_MIXIN_KEY_ENC_TAB)[:32]
        sorted_items = {"a": "x! y", "b": "2", "wts": 123}
        expected_query = "&".join(
            f"{urllib.parse.quote(str(key), safe='')}="
            f"{urllib.parse.quote(str(value).replace('!', ''), safe='')}"
            for key, value in sorted_items.items()
        )
        expected_rid = hashlib.md5(
            (expected_query + mixin_key).encode("utf-8")
        ).hexdigest()
        self.assertEqual(signed["wts"], 123)
        self.assertEqual(signed["w_rid"], expected_rid)
        self.assertEqual(encode_query({"a": "x!()*"}), "a=x")

    def test_profile_and_cookie_helpers(self) -> None:
        validate_nav_payload({"code": 0})
        validate_nav_payload({"code": -101})
        with self.assertRaisesRegex(ValueError, "登录状态异常"):
            validate_nav_payload({"code": -400, "message": "bad"})

        self.assertEqual(parse_self_info({"data": {"isLogin": False}}), (None, ""))
        self.assertEqual(
            parse_self_info({"data": {"isLogin": True, "mid": "42", "uname": "user"}}),
            (42, "user"),
        )
        self.assertEqual(
            parse_self_info({"data": {"isLogin": True, "mid": 0, "uname": "ghost"}}),
            (None, "ghost"),
        )

        cookie_map, cookie_header, bili_jct = build_cookie_state(
            "SESSDATA=x; bili_jct=csrf; DedeUserID=1",
            fallback_buvid3="existing",
        )
        self.assertEqual(cookie_map["buvid3"], "existing")
        self.assertEqual(bili_jct, "csrf")
        self.assertIn("bili_jct=csrf", cookie_header)
        self.assertEqual(
            build_live_headers(
                123,
                user_agent=DEFAULT_USER_AGENT,
                cookie_header=cookie_header,
                lite=True,
            )["Referer"],
            "https://live.bilibili.com/blanc/123?liteVersion=true",
        )
        self.assertTrue(
            build_mission_headers(
                "task id",
                user_agent=DEFAULT_USER_AGENT,
                cookie_header=cookie_header,
            )["Referer"].endswith("task_id=task%20id")
        )


class BilibiliClientNavTest(unittest.TestCase):
    def _make_client(self) -> core_module.BilibiliClient:
        return core_module.BilibiliClient("SESSDATA=x; bili_jct=csrf")

    def test_nav_retries_transient_connect_error(self) -> None:
        client = self._make_client()
        calls = {"n": 0}

        class _Resp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"code": 0, "data": {"isLogin": False}}

        async def fake_get(_url: str):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectTimeout("boom")
            return _Resp()

        async def exercise():
            with unittest.mock.patch.object(client._http, "get", fake_get):
                return await client.nav()

        try:
            payload = asyncio.run(exercise())
        finally:
            asyncio.run(client.close())

        self.assertEqual(calls["n"], 2)
        self.assertEqual(payload["code"], 0)

    def test_nav_raises_contextual_error_for_non_json_body(self) -> None:
        client = self._make_client()

        class _HtmlResp:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self):
                raise ValueError("Expecting value")

        async def exercise():
            with unittest.mock.patch.object(
                client._http, "get", lambda _url: _async_return(_HtmlResp())
            ):
                return await client.nav()

        try:
            with self.assertRaisesRegex(RuntimeError, "非 JSON"):
                asyncio.run(exercise())
        finally:
            asyncio.run(client.close())

    def test_wbi_keys_concurrent_miss_single_flight(self) -> None:
        client = self._make_client()
        nav_calls: list[int] = []

        img_key = "abcdefghijklmnopqrstuvwxyzabcdef"
        sub_key = "1234567890abcdef1234567890abcdef"
        payload = {
            "data": {
                "wbi_img": {
                    "img_url": f"https://i0.hdslb.com/bfs/wbi/{img_key}.png",
                    "sub_url": f"https://i0.hdslb.com/bfs/wbi/{sub_key}.png",
                }
            }
        }

        async def slow_nav():
            nav_calls.append(1)
            await asyncio.sleep(0.01)
            return payload

        async def exercise():
            with unittest.mock.patch.object(client, "nav", slow_nav):
                return await asyncio.gather(
                    *(client.get_wbi_keys() for _ in range(5))
                )

        try:
            results = asyncio.run(exercise())
        finally:
            asyncio.run(client.close())

        # 并发 miss 只应发起一次 nav 请求（单飞），所有调用拿到同一份缓存
        self.assertEqual(len(nav_calls), 1)
        self.assertTrue(all(r == results[0] for r in results))


def _async_return(value):
    future = asyncio.get_event_loop().create_future()
    future.set_result(value)
    return future


if __name__ == "__main__":
    unittest.main()
