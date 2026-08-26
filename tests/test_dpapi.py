from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from overwatch_drops_miner import dpapi


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class DpapiTest(unittest.TestCase):
    def test_protect_unprotect_roundtrip(self) -> None:
        secret = "SESSDATA=abc; bili_jct=def; DedeUserID=123"
        encrypted = dpapi.protect(secret)
        self.assertNotEqual(encrypted, secret)
        self.assertNotIn("SESSDATA", encrypted)
        self.assertEqual(dpapi.unprotect(encrypted), secret)

    def test_unprotect_rejects_invalid_data(self) -> None:
        with self.assertRaises((ValueError, OSError)):
            dpapi.unprotect("not-valid-ciphertext")


if __name__ == "__main__":
    unittest.main()



class DpapiFailureBranchTest(unittest.TestCase):
    """T-6 盲区：DPAPI 调用失败与 LocalFree 异常路径。"""

    def test_protect_raises_oserror_when_api_fails(self) -> None:
        from unittest import mock

        from overwatch_drops_miner import dpapi

        with mock.patch.object(dpapi._crypt32, "CryptProtectData", return_value=0):
            with self.assertRaises(OSError) as ctx:
                dpapi.protect("secret")
            # use_last_error 采集链路：错误信息里应带 WinError 描述
            self.assertIn("CryptProtectData", str(ctx.exception))

    def test_local_free_failure_does_not_break_unprotect(self) -> None:
        from unittest import mock

        from overwatch_drops_miner import dpapi

        cipher = dpapi.protect("hello")
        with mock.patch.object(dpapi._kernel32, "LocalFree", return_value=1):
            # LocalFree 失败仅告警，不影响解密结果
            self.assertEqual(dpapi.unprotect(cipher), "hello")

