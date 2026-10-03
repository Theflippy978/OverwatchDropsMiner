from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from python_sidecar.backend import paths


class PathsTest(unittest.TestCase):
    def test_default_config_dir_uses_appdata(self) -> None:
        original = os.environ.pop(paths.CONFIG_DIR_ENV_VAR, None)
        try:
            os.environ["APPDATA"] = os.path.join(tempfile.gettempdir(), "appdata-test")
            config_dir = paths.get_config_dir()
            self.assertEqual(config_dir.name, paths.APP_DATA_DIR_NAME)
            self.assertEqual(
                paths.get_accounts_path(),
                config_dir / paths.ACCOUNTS_FILE_NAME,
            )
        finally:
            os.environ.pop("APPDATA", None)
            if original is not None:
                os.environ[paths.CONFIG_DIR_ENV_VAR] = original

    def test_env_var_redirects_all_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ[paths.CONFIG_DIR_ENV_VAR] = temp_dir
            try:
                self.assertTrue(paths.is_isolated())
                self.assertEqual(paths.get_config_dir(), Path(temp_dir).resolve())
                self.assertEqual(
                    paths.get_accounts_path(),
                    Path(temp_dir) / paths.ACCOUNTS_FILE_NAME,
                )
            finally:
                os.environ.pop(paths.CONFIG_DIR_ENV_VAR, None)
        self.assertFalse(paths.is_isolated())

    def test_relative_config_dir_resolves_to_absolute(self) -> None:
        # 回归：OW_CONFIG_DIR 为相对路径时应固化为绝对路径，
        # 避免工作目录变化后配置读写位置漂移
        original = os.environ.pop(paths.CONFIG_DIR_ENV_VAR, None)
        try:
            os.environ[paths.CONFIG_DIR_ENV_VAR] = "relative-config-dir"
            config_dir = paths.get_config_dir()
            self.assertTrue(config_dir.is_absolute())
            self.assertEqual(config_dir.name, "relative-config-dir")
        finally:
            os.environ.pop(paths.CONFIG_DIR_ENV_VAR, None)
            if original is not None:
                os.environ[paths.CONFIG_DIR_ENV_VAR] = original


if __name__ == "__main__":
    unittest.main()
