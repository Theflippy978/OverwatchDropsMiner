from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from overwatch_drops_miner.accounts import AccountStore
from overwatch_drops_miner import dpapi


class AccountStoreTest(unittest.TestCase):
    def test_add_get_remove_roundtrip_with_encryption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            store = AccountStore(path=path)

            account = store.add("SESSDATA=abc; bili_jct=def", remark="测试账号")
            self.assertEqual(account.remark, "测试账号")
            self.assertNotIn("SESSDATA", path.read_text(encoding="utf-8"))
            self.assertEqual(store.list_accounts(), [account])
            self.assertEqual(account.cookie(), "SESSDATA=abc; bili_jct=def")

            reloaded = AccountStore(path=path)
            loaded = reloaded.get(account.id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.remark, "测试账号")
            self.assertEqual(loaded.cookie(), "SESSDATA=abc; bili_jct=def")

            self.assertTrue(reloaded.remove(account.id))
            self.assertIsNone(reloaded.get(account.id))
            self.assertFalse(reloaded.remove(account.id))

    def test_update_remark_and_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            store = AccountStore(path=path)
            account = store.add("cookie-old", remark="旧备注")

            updated = store.update(account.id, remark="新备注", cookie="cookie-new")
            self.assertEqual(updated.remark, "新备注")
            self.assertEqual(updated.cookie(), "cookie-new")

            remark_only = store.update(account.id, remark="仅改备注")
            self.assertEqual(remark_only.remark, "仅改备注")
            self.assertEqual(remark_only.cookie(), "cookie-new")

    def test_empty_store_creates_no_file_until_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            AccountStore(path=path)
            self.assertFalse(path.exists())
            store = AccountStore(path=path)
            store.add("cookie", remark="x")
            self.assertTrue(path.exists())

    def test_corrupt_file_loads_as_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            path.write_text("not json", encoding="utf-8")
            store = AccountStore(path=path)
            self.assertEqual(store.list_accounts(), [])


if __name__ == "__main__":
    unittest.main()
