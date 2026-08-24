from __future__ import annotations

import json
import unittest

from overwatch_drops_miner.utils import (
    extract_bili_live_task_groups,
    join_cookie,
    parse_cookie,
    parse_room_ids,
    parse_url_list,
)


def _task_group(task_id: str) -> dict:
    return {"tasklist": [{"taskId": task_id}]}


def _panel(panel_id: str, label: str) -> dict:
    return {
        "id": panel_id,
        "tabItem": {"tabItemProps": {"textContent": {"content": label}}},
    }


def _component(name: str, props: dict, children: list[dict] | None = None) -> dict:
    return {
        "type": "Component",
        "name": name,
        "props": props,
        "slots": [{"children": children or []}],
    }


class ExtractBiliLiveTaskGroupsTests(unittest.TestCase):
    def test_extracts_new_eva_layer_tree_and_preserves_groups(self) -> None:
        yesterday_panel = _component(
            "EvaTabs.Panel",
            _panel("yesterday", "昨天"),
            [_component("EraTasklistPc", _task_group("old-task"))],
        )
        today_panel = _component(
            "EvaTabs.Panel",
            _panel("today", "今天"),
            [
                _component("EraTasklistPc", _task_group("today-a")),
                _component("EraTasklistPc", _task_group("today-b")),
            ],
        )
        tabs = _component(
            "EvaTabs",
            {"activatedTabPanelId": "today"},
            [yesterday_panel, today_panel],
        )
        page_data = {"layerTree": _component("Root", {}, [tabs])}
        html = (
            '<script>window.__initialState = {"BaseInfo": {}};</script>'
            "<script>window.__BILIACT_EVAPAGEDATA__ = "
            f"{json.dumps(page_data)};</script>"
        )

        self.assertEqual(
            extract_bili_live_task_groups(html),
            [
                {"label": "昨天", "task_ids": ["old-task"], "active": False},
                {
                    "label": "今天",
                    "task_ids": ["today-a", "today-b"],
                    "active": True,
                },
            ],
        )

    def test_extracts_legacy_initial_state(self) -> None:
        state = {
            "EraTasklistPc": [_task_group("legacy-task")],
            "EvaPositionBox": [{"left": 0, "top": 0}],
            "EvaTabs.Panel": [_panel("legacy", "旧活动")],
            "EvaTabs": [{"activatedTabPanelId": "legacy"}],
        }
        html = f"<script>window.__initialState = {json.dumps(state)};</script>"

        self.assertEqual(
            extract_bili_live_task_groups(html),
            [
                {
                    "label": "旧活动",
                    "task_ids": ["legacy-task"],
                    "active": True,
                }
            ],
        )

    def test_returns_empty_for_missing_or_invalid_page_data(self) -> None:
        invalid_pages = [
            "",
            "<html>no state</html>",
            '<script>window.__BILIACT_EVAPAGEDATA__ = {"layerTree": [};</script>',
            '<script>window.__initialState = {"EraTasklistPc": [};</script>',
        ]

        for html in invalid_pages:
            with self.subTest(html=html):
                self.assertEqual(extract_bili_live_task_groups(html), [])


class CookieParsingTests(unittest.TestCase):
    def test_parse_cookie_multiline_not_swallowed(self) -> None:
        # 跨行 Cookie 各键应独立解析，第一行 value 不能吞并第二行内容
        cookie_map = parse_cookie("SESSDATA=abc\nbili_jct=xyz")
        self.assertEqual(cookie_map, {"SESSDATA": "abc", "bili_jct": "xyz"})

    def test_parse_cookie_strips_whitespace(self) -> None:
        # 值两端空白应被去除，避免尾随空格导致签名失败
        cookie_map = parse_cookie("bili_jct=abc ; x=1")
        self.assertEqual(cookie_map, {"bili_jct": "abc", "x": "1"})

    def test_join_cookie_removes_breaking_characters(self) -> None:
        # 防御性：值中含分号/换行时应剔除，避免破坏 Cookie 头结构
        header = join_cookie({"a": "x;y", "b": "p\nq"})
        self.assertEqual(header, "a=xy; b=pq")


class ParseRoomIdsTests(unittest.TestCase):
    def test_superscript_digit_raises_custom_value_error(self) -> None:
        # '²'.isdigit() 为 True 但 int() 会抛裸异常，
        # 必须统一抛出项目自定义的“房间号格式错误”
        with self.assertRaisesRegex(ValueError, "房间号格式错误"):
            parse_room_ids("12²")

    def test_normal_room_ids_parse(self) -> None:
        self.assertEqual(parse_room_ids("1, 2\n3"), [1, 2, 3])


class ParseUrlListTests(unittest.TestCase):
    def test_parse_url_list_basic(self) -> None:
        # 逗号/换行混合分隔、去重、含 & 的 URL 必须完整保留（不做截断）
        raw = (
            "https://example.com/hook?a=1&b=2,\n"
            "https://example.com/hook?a=1&b=2\n\n"
            "  https://example.com/other  ,"
        )
        self.assertEqual(
            parse_url_list(raw),
            [
                "https://example.com/hook?a=1&b=2",
                "https://example.com/other",
            ],
        )
        self.assertEqual(parse_url_list(""), [])
        self.assertEqual(parse_url_list("   \n  ,  "), [])


if __name__ == "__main__":
    unittest.main()
