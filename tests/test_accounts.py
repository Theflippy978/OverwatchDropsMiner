from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from python_sidecar.backend.accounts import AccountStore


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

    def test_save_atomic_no_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            store = AccountStore(path=path)
            account = store.add("cookie-a", remark="a")
            original = path.read_text(encoding="utf-8")

            def broken_replace(src, dst):
                raise OSError("模拟替换失败")

            with unittest.mock.patch(
                "python_sidecar.backend.accounts.os.replace",
                side_effect=broken_replace,
            ):
                with self.assertRaises(OSError):
                    store.add("cookie-b", remark="b")

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(store.get(account.id).remark, "a")
            # 磁盘原文件未被破坏：重新加载仍只有原账号
            reloaded = AccountStore(path=path)
            self.assertEqual(
                [item.remark for item in reloaded.list_accounts()], ["a"]
            )
            # 原子写失败后临时文件残留不影响下次保存
            store.add("cookie-c", remark="c")
            reloaded = AccountStore(path=path)
            self.assertEqual(len(reloaded.list_accounts()), 3)

    def test_load_corrupt_file_backed_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            path.write_text("{broken json", encoding="utf-8")

            store = AccountStore(path=path)

            backups = list(Path(temp_dir).glob("accounts.json.corrupt-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken json")
            self.assertFalse(path.exists())
            self.assertEqual(store.list_accounts(), [])

    def test_load_non_utf8_file_no_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            path.write_bytes(b"\xff\xfe\x00bad")

            store = AccountStore(path=path)

            self.assertEqual(store.list_accounts(), [])
            self.assertTrue(list(Path(temp_dir).glob("accounts.json.corrupt-*")))


if __name__ == "__main__":
    unittest.main()



class ConcurrentSaveTest(unittest.TestCase):
    """T-5/B-2 盲区：并发保存的数据完整性与临时文件清理。"""

    def test_concurrent_saves_keep_store_consistent(self) -> None:
        import threading

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "accounts.json"
            store = AccountStore(path=path)
            store.add("SESSDATA=s1", remark="a")

            errors: list[Exception] = []

            def worker(index: int) -> None:
                try:
                    for round_index in range(5):
                        store.save()
                        assert path.exists()
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

            threads = [
                threading.Thread(target=worker, args=(i,)) for i in range(4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            reloaded = AccountStore(path=path)
            self.assertEqual(len(reloaded.list_accounts()), 1)
            # 无 .tmp* 残留（唯一临时名 + replace 后应全部消失）
            leftovers = list(Path(temp_dir).glob("accounts.json.tmp*"))
            self.assertEqual(leftovers, [])

