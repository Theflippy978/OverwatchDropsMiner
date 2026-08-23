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
