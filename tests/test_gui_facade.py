from __future__ import annotations

import unittest

import overwatch_drops_miner.gui as gui_facade
import overwatch_drops_miner.gui_parts.main_window as main_window


class TestGuiFacade(unittest.TestCase):
    def test_reexports_main_window_objects(self) -> None:
        self.assertIs(gui_facade.MinerGUI, main_window.MinerGUI)
        self.assertIs(gui_facade.run_gui, main_window.run_gui)
        self.assertEqual(gui_facade.APP_VERSION, main_window.APP_VERSION)
        self.assertEqual(gui_facade.UPDATE_CHANNEL, main_window.UPDATE_CHANNEL)
        self.assertEqual(gui_facade.LATEST_RELEASE_API, main_window.LATEST_RELEASE_API)
        self.assertEqual(gui_facade.RELEASES_URL, main_window.RELEASES_URL)
        self.assertIs(gui_facade._normalize_version, main_window._normalize_version)

    def test_facade_all_exports_expected_names(self) -> None:
        self.assertEqual(
            gui_facade.__all__,
            [
                "APP_VERSION",
                "LATEST_RELEASE_API",
                "RELEASES_URL",
                "UPDATE_CHANNEL",
                "MinerGUI",
                "_normalize_version",
                "run_gui",
            ],
        )


if __name__ == "__main__":
    unittest.main()
