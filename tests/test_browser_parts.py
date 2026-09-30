from __future__ import annotations

import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from overwatch_drops_miner.gui_parts import browser_sniffer as browser_sniffer_module
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
