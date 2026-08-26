from __future__ import annotations

import unittest

from overwatch_drops_miner.gui_parts.update_checker import (
    normalize_version,
    parse_update_payload,
    should_check_update,
)


class NormalizeVersionTest(unittest.TestCase):
    def test_strips_v_prefix_and_whitespace(self) -> None:
        self.assertEqual(normalize_version(" V1.2.3 "), "1.2.3")
        self.assertEqual(normalize_version("v0.9"), "0.9")


class ShouldCheckUpdateTest(unittest.TestCase):
    def test_release_channel_with_real_version(self) -> None:
        self.assertTrue(should_check_update("1.2.3", "release"))

    def test_dev_channel_skips_check(self) -> None:
        self.assertFalse(should_check_update("1.2.3", "dev"))

    def test_dev_embedded_version_skips_check(self) -> None:
        # 形如 dev-abcdef 的版本串不应触发更新检查
        self.assertFalse(should_check_update("dev-abcdef", "release"))

    def test_plus_dev_suffix_skips_check(self) -> None:
        self.assertFalse(should_check_update("0.0.0+dev", "release"))

    def test_empty_version_skips_check(self) -> None:
        self.assertFalse(should_check_update("", "release"))


class ParseUpdatePayloadTest(unittest.TestCase):
    def test_newer_version_returns_result(self) -> None:
        result = parse_update_payload(
            {"tag_name": "v2.0.0", "html_url": "https://example.invalid/r"},
            current_version="1.0.0",
            releases_url="https://example.invalid/releases",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.latest_version, "v2.0.0")

    def test_missing_tag_returns_none(self) -> None:
        self.assertIsNone(
            parse_update_payload({}, current_version="1.0.0", releases_url="u")
        )

    def test_older_or_equal_tag_returns_none(self) -> None:
        self.assertIsNone(
            parse_update_payload(
                {"tag_name": "v1.0.0"}, current_version="1.0.0", releases_url="u"
            )
        )
        self.assertIsNone(
            parse_update_payload(
                {"tag_name": "v0.9"}, current_version="1.0.0", releases_url="u"
            )
        )


if __name__ == "__main__":
    unittest.main()
