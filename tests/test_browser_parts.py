from __future__ import annotations

import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QMessageBox

from overwatch_drops_miner.gui_parts import browser_sniffer as browser_sniffer_module
from overwatch_drops_miner.gui_parts.browser_actions import BrowserActions
from overwatch_drops_miner.gui_parts.browser_sniffer import (
    classify_sniff_payload,
    is_sniff_finished,
    select_login_cookies,
)
from overwatch_drops_miner.gui_parts.browser_utils import (
    browser_label,
    browser_try_order,
    extract_room_id_from_live_url,
)
from overwatch_drops_miner.gui_parts.extension_builder import (
    build_page_reporter_js,
    write_chrome_extension,
    write_edge_extension,
)


class BrowserUtilsTest(unittest.TestCase):
    def test_extract_room_id_from_live_url(self) -> None:
        self.assertEqual(
            extract_room_id_from_live_url("https://live.bilibili.com/23612045"),
            23612045,
        )
        self.assertEqual(
            extract_room_id_from_live_url("https://live.bilibili.com/blanc/6?x=1"),
            6,
        )
        self.assertEqual(
            extract_room_id_from_live_url("live.bilibili.com/12345"),
            12345,
        )
        self.assertIsNone(extract_room_id_from_live_url("https://www.bilibili.com/"))
        self.assertIsNone(extract_room_id_from_live_url(""))

    def test_browser_try_order_prefers_selected_then_default(self) -> None:
        with patch(
            "overwatch_drops_miner.gui_parts.browser_utils.find_browser",
            side_effect=lambda browser: browser in {"chrome", "edge"},
        ), patch(
            "overwatch_drops_miner.gui_parts.browser_utils.detect_default_browser",
            return_value="edge",
        ):
            self.assertEqual(browser_try_order("chrome"), ("chrome", "edge"))
            self.assertEqual(browser_try_order(None), ("edge", "chrome"))

    def test_browser_label_fallback(self) -> None:
        self.assertEqual(browser_label("chrome"), "Google Chrome")
        self.assertEqual(browser_label("edge"), "Microsoft Edge")
        self.assertEqual(browser_label("other"), "other")


class ExtensionBuilderTest(unittest.TestCase):
    def test_page_reporter_contains_expected_payload_marker(self) -> None:
        script = build_page_reporter_js(54321)

        self.assertIn("http://127.0.0.1:54321/", script)
        self.assertIn("__bili_page__", script)
        self.assertIn("live.bilibili.com", script)

    def test_write_edge_extension_generates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_edge_extension(
                tmpdir,
                port=12345,
                url_keyword="/x/task/totalv2",
                need_net=True,
                need_cookie=True,
                need_page=True,
            )
            ext_dir = Path(tmpdir)

            manifest = json.loads((ext_dir / "manifest.json").read_text())
            self.assertEqual(manifest["manifest_version"], 3)
            self.assertIn("cookies", manifest["permissions"])
            self.assertEqual(manifest["background"], {"service_worker": "background.js"})
            self.assertTrue((ext_dir / "inject.js").exists())
            self.assertTrue((ext_dir / "relay.js").exists())
            self.assertTrue((ext_dir / "page.js").exists())
            self.assertTrue((ext_dir / "background.js").exists())
            self.assertIn("__bili_sniff__", (ext_dir / "inject.js").read_text())
            self.assertIn("/x/task/totalv2", (ext_dir / "inject.js").read_text())
            self.assertIn("__bili_cookies__", (ext_dir / "background.js").read_text())
            self.assertIn("__bili_page__", (ext_dir / "page.js").read_text())

    def test_write_chrome_extension_generates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            write_chrome_extension(
                tmpdir,
                port=23456,
                url_keyword="/x/task/totalv2",
                need_net=True,
                need_cookie=True,
                need_page=True,
            )
            ext_dir = Path(tmpdir)

            manifest = json.loads((ext_dir / "manifest.json").read_text())
            self.assertEqual(manifest["manifest_version"], 3)
            self.assertIn("scripting", manifest["permissions"])
            self.assertIn("cookies", manifest["permissions"])
            self.assertEqual(manifest["background"], {"service_worker": "background.js"})
            self.assertTrue((ext_dir / "relay.js").exists())
            self.assertTrue((ext_dir / "page.js").exists())
            self.assertTrue((ext_dir / "background.js").exists())
            self.assertIn("__bili_sniff__", (ext_dir / "relay.js").read_text())
            self.assertIn("/x/task/totalv2", (ext_dir / "background.js").read_text())
            self.assertIn("__bili_cookies__", (ext_dir / "background.js").read_text())
            self.assertIn("__bili_page__", (ext_dir / "page.js").read_text())


class BrowserSnifferTest(unittest.TestCase):
    def test_classify_sniff_payload(self) -> None:
        self.assertEqual(
            classify_sniff_payload({"type": "__bili_cookies__", "cookies": [1]}),
            ("cookies", [1]),
        )
        page_payload = {"type": "__bili_page__", "url": "u", "html": "h"}
        self.assertEqual(classify_sniff_payload(page_payload), ("page", page_payload))
        network_payload = {"url": "u", "data": {"code": 0}}
        self.assertEqual(
            classify_sniff_payload(network_payload),
            ("network", network_payload),
        )

    def test_select_login_cookies_requires_sessdata_and_dede_user_id(self) -> None:
        cookies = [
            {"name": "SESSDATA", "value": "sess"},
            {"name": "DedeUserID", "value": "1"},
            {"name": "bili_jct", "value": "csrf"},
            {"name": "unrelated", "value": "ignored"},
        ]

        filtered = select_login_cookies(cookies)
        self.assertIsNotNone(filtered)
        self.assertEqual(
            {cookie["name"] for cookie in filtered or []},
            {"SESSDATA", "DedeUserID", "bili_jct"},
        )
        self.assertIsNone(select_login_cookies(cookies[:1]))

    def test_is_sniff_finished_any_and_all_modes(self) -> None:
        self.assertFalse(is_sniff_finished([], finish_on_any=True))
        self.assertTrue(
            is_sniff_finished(
                [(True, False), (True, True), (False, False)],
                finish_on_any=True,
            )
        )
        self.assertFalse(
            is_sniff_finished(
                [(True, False), (True, True)],
                finish_on_any=False,
            )
        )
        self.assertTrue(
            is_sniff_finished(
                [(True, True), (True, True), (False, False)],
                finish_on_any=False,
            )
        )


class BrowserActionsTest(unittest.TestCase):
    class _ImmediateThread:
        def __init__(self, *, target, **_kwargs) -> None:
            self.target = target

        def start(self) -> None:
            self.target()

    def _build_actions(self) -> tuple[BrowserActions, dict[str, list]]:
        events: dict[str, list] = {
            "warnings": [],
            "errors": [],
            "rooms": [],
            "cookies": [],
            "task_ids": [],
        }

        def post_ui_task(callback, *args, **kwargs) -> None:
            callback(*args, **kwargs)

        actions = BrowserActions(
            parent=None,
            show_warning=lambda title, msg: events["warnings"].append((title, msg)),
            show_error=lambda title, msg: events["errors"].append((title, msg)),
            post_ui_task=post_ui_task,
            set_room_id=events["rooms"].append,
            set_cookie=events["cookies"].append,
            set_task_ids=events["task_ids"].append,
        )
        return actions, events

    def test_pick_browser_warns_when_none_available(self) -> None:
        actions, events = self._build_actions()

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.available_browsers",
            return_value=[],
        ):
            self.assertIsNone(actions.pick_browser())

        self.assertEqual(
            events["warnings"],
            [("提示", "未检测到 Chrome 或 Edge，请先安装浏览器。")],
        )

    def test_apply_selected_task_group_applies_active_group(self) -> None:
        actions, events = self._build_actions()
        task_groups = [
            {"label": "昨天", "task_ids": ["old"]},
            {"label": "今天", "task_ids": ["task-a", "task-b"], "active": True},
        ]

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.QInputDialog.getItem",
            return_value=("今天 (2 个任务)", True),
        ):
            actions.apply_selected_task_group(23612045, task_groups)

        self.assertEqual(events["rooms"], [23612045])
        self.assertEqual(events["task_ids"], ["task-a,task-b"])
        self.assertEqual(events["warnings"], [])

    def test_browser_sniff_routes_error_to_ui_callback(self) -> None:
        actions, events = self._build_actions()

        def fake_start_browser_sniff(*_args, **kwargs) -> None:
            kwargs["on_error"]("错误", "浏览器启动失败")

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.start_browser_sniff",
            side_effect=fake_start_browser_sniff,
        ):
            actions.browser_sniff(None, "hint")

        self.assertEqual(events["errors"], [("错误", "浏览器启动失败")])

    def test_auto_fetch_task_ids_mode1_posts_static_groups_without_sniff(self) -> None:
        actions, _events = self._build_actions()
        groups = [{"label": "今天", "task_ids": ["task-a"], "active": True}]

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.fetch_live_task_groups",
            return_value=groups,
        ) as fetch, patch(
            "overwatch_drops_miner.gui_parts.browser_actions.threading.Thread",
            self._ImmediateThread,
        ), patch.object(
            actions, "apply_selected_task_group"
        ) as apply_group, patch.object(
            actions, "browser_sniff"
        ) as browser_sniff:
            actions.auto_fetch_task_ids_mode1(23612045)

        fetch.assert_called_once_with(23612045)
        apply_group.assert_called_once_with(23612045, groups)
        browser_sniff.assert_not_called()

    def test_auto_fetch_task_ids_mode1_suggests_mode2_on_empty_or_error(self) -> None:
        actions, events = self._build_actions()

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.threading.Thread",
            self._ImmediateThread,
        ), patch(
            "overwatch_drops_miner.gui_parts.browser_actions.fetch_live_task_groups",
            return_value=[],
        ):
            actions.auto_fetch_task_ids_mode1(23612045)

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.threading.Thread",
            self._ImmediateThread,
        ), patch(
            "overwatch_drops_miner.gui_parts.browser_actions.fetch_live_task_groups",
            side_effect=RuntimeError("sensitive response body"),
        ):
            actions.auto_fetch_task_ids_mode1(23612045)

        self.assertIn("模式2", events["warnings"][0][1])
        self.assertIn("模式2", events["errors"][0][1])
        self.assertNotIn("sensitive", events["errors"][0][1])

    def test_auto_fetch_task_ids_handles_network_payload(self) -> None:
        actions, events = self._build_actions()

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.QMessageBox.question",
            return_value=QMessageBox.Ok,
        ), patch.object(BrowserActions, "pick_browser", return_value="chrome"), patch.object(
            BrowserActions,
            "browser_sniff",
        ) as browser_sniff:
            actions.auto_fetch_task_ids_mode2()

        self.assertEqual(browser_sniff.call_args.kwargs["browser_preference"], "chrome")
        self.assertTrue(browser_sniff.call_args.kwargs["finish_on_any"])
        on_match = browser_sniff.call_args.kwargs["on_network_match"]
        on_match(
            {
                "page_url": "https://live.bilibili.com/23612045",
                "data": {
                    "code": 0,
                    "data": {"list": [{"task_id": "task-a"}, {"task_id": "task-b"}]},
                },
            }
        )

        self.assertEqual(events["rooms"], [23612045])
        self.assertEqual(events["task_ids"], ["task-a,task-b"])

    def test_auto_fetch_task_ids_uses_room_start_url_or_bilibili_home(self) -> None:
        actions, _events = self._build_actions()

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.QMessageBox.question",
            return_value=QMessageBox.Ok,
        ), patch.object(BrowserActions, "pick_browser", return_value="chrome"), patch.object(
            BrowserActions,
            "browser_sniff",
        ) as browser_sniff:
            actions.auto_fetch_task_ids_mode2(23612045)
            self.assertEqual(
                browser_sniff.call_args.kwargs["start_url"],
                "https://live.bilibili.com/23612045",
            )

            actions.auto_fetch_task_ids_mode2()
            self.assertIsNone(browser_sniff.call_args.kwargs["start_url"])

    def test_auto_fetch_cookie_applies_filtered_cookie_string(self) -> None:
        actions, events = self._build_actions()

        with patch(
            "overwatch_drops_miner.gui_parts.browser_actions.QMessageBox.question",
            return_value=QMessageBox.Ok,
        ), patch.object(BrowserActions, "pick_browser", return_value="edge"), patch.object(
            BrowserActions,
            "browser_sniff",
        ) as browser_sniff:
            actions.auto_fetch_cookie()

        self.assertEqual(browser_sniff.call_args.kwargs["browser_preference"], "edge")
        on_cookies = browser_sniff.call_args.kwargs["on_cookies"]
        on_cookies(
            [
                {"name": "SESSDATA", "value": "sess"},
                {"name": "DedeUserID", "value": "1"},
            ]
        )

        self.assertEqual(events["cookies"], ["SESSDATA=sess; DedeUserID=1"])


    def test_browser_actions_shutdown_joins_sniff_thread(self) -> None:
        actions, _events = self._build_actions()
        release = threading.Event()
        worker_started = threading.Event()

        def slow_worker() -> None:
            worker_started.set()
            release.wait(timeout=5)

        thread = threading.Thread(target=slow_worker, daemon=True)
        thread.start()
        self.assertTrue(worker_started.wait(timeout=5))
        actions._sniff_thread = thread
        actions._sniff_cancel.clear()

        results: list[bool] = []
        # shutdown 会阻塞等待 join，放到独立线程中执行
        shutter = threading.Thread(
            target=lambda: results.append(actions.shutdown(timeout=0.3)),
            daemon=True,
        )
        shutter.start()
        shutter.join(timeout=5)

        self.assertEqual(results, [False])
        self.assertTrue(actions._sniff_cancel.is_set())

        release.set()
        thread.join(timeout=5)
        self.assertTrue(actions.shutdown())
        self.assertFalse(thread.is_alive())

    @staticmethod
    def _build_fake_selenium() -> tuple[types.ModuleType, types.ModuleType, type, type]:
        class _FakeOptions:
            binary_location = None

            def __init__(self) -> None:
                self.args: list[str] = []

            def add_argument(self, arg: str) -> None:
                self.args.append(arg)

        class _FakeChrome:
            instances: list[_FakeChrome] = []

            def __init__(self, options=None) -> None:
                self.options = options
                self.webextension = Mock()
                self.quit = Mock()
                self.get = Mock()
                type(self).instances.append(self)

        class _FakeEdge(_FakeChrome):
            instances: list[_FakeEdge] = []

        fake_selenium = types.ModuleType("selenium")
        fake_webdriver = types.ModuleType("selenium.webdriver")
        fake_webdriver.ChromeOptions = _FakeOptions  # type: ignore[attr-defined]
        fake_webdriver.EdgeOptions = _FakeOptions  # type: ignore[attr-defined]
        fake_webdriver.Chrome = _FakeChrome  # type: ignore[attr-defined]
        fake_webdriver.Edge = _FakeEdge  # type: ignore[attr-defined]
        fake_selenium.webdriver = fake_webdriver
        return fake_selenium, fake_webdriver, _FakeChrome, _FakeEdge

    def _run_sniff_with_fakes(
        self,
        cancel_event: object,
        on_error: Mock,
    ) -> tuple[type, type]:
        (
            fake_selenium,
            fake_webdriver,
            fake_chrome_cls,
            fake_edge_cls,
        ) = self._build_fake_selenium()

        with patch.dict(
            sys.modules,
            {"selenium": fake_selenium, "selenium.webdriver": fake_webdriver},
        ), patch.object(
            browser_sniffer_module, "find_browser", return_value=True
        ), patch.object(
            browser_sniffer_module, "find_browser_binary", return_value=None
        ), patch.object(
            browser_sniffer_module, "write_chrome_extension"
        ), patch.object(
            browser_sniffer_module, "write_edge_extension"
        ), patch(
            "overwatch_drops_miner.gui_parts.browser_utils.detect_default_browser",
            return_value="edge",
        ):
            thread = browser_sniffer_module.start_browser_sniff(
                None,
                "测试提示",
                on_error=on_error,
                cancel_event=cancel_event,  # type: ignore[arg-type]
            )
            thread.join(timeout=10)

        self.assertFalse(thread.is_alive())
        return fake_chrome_cls, fake_edge_cls

    def test_sniffer_loop_respects_cancel_event(self) -> None:
        cancel_event = threading.Event()
        cancel_event.set()
        on_error = Mock()

        _FakeChrome, FakeEdge = self._run_sniff_with_fakes(cancel_event, on_error)

        drivers = FakeEdge.instances
        self.assertEqual(len(drivers), 1)
        drivers[0].quit.assert_called_once()
        on_error.assert_not_called()

    def test_sniffer_timeout_reports_error(self) -> None:
        class _NoWaitEvent:
            def __init__(self) -> None:
                self.cancelled = False

            def is_set(self) -> bool:
                return self.cancelled

            def wait(self, _timeout: float | None = None) -> bool:
                return False

        cancel_event = _NoWaitEvent()
        on_error = Mock()

        _FakeChrome, FakeEdge = self._run_sniff_with_fakes(cancel_event, on_error)

        drivers = FakeEdge.instances
        self.assertEqual(len(drivers), 1)
        drivers[0].quit.assert_called_once()
        on_error.assert_called_once()
        self.assertIn("2 分钟", str(on_error.call_args.args[1]))


if __name__ == "__main__":
    unittest.main()
