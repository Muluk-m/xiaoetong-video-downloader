#!/usr/bin/env python
# -*- coding: utf-8 -*-

import ctypes
import hashlib
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from xiaoet_downloader.utils.chrome_cookies import (
    KeychainAccessError,
    _CHROMIUM_EPOCH_OFFSET_SECONDS,
    _derive_macos_chrome_key,
    extract_chrome_cookies,
    merge_cookies,
)


def _aes_128_cbc_encrypt_macos(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """测试辅助：使用 macOS CommonCrypto 加密模拟 Chrome v10 Cookie"""
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
    lib.CCCrypt.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.CCCrypt.restype = ctypes.c_int32
    out_buf = ctypes.create_string_buffer(len(plaintext) + 16)
    moved = ctypes.c_size_t(0)
    status = lib.CCCrypt(
        0,  # kCCEncrypt
        0,  # kCCAlgorithmAES128
        1,  # kCCOptionPKCS7Padding
        key,
        len(key),
        iv,
        plaintext,
        len(plaintext),
        out_buf,
        len(out_buf),
        ctypes.byref(moved),
    )
    assert status == 0, f"CCCrypt encrypt failed: {status}"
    return out_buf.raw[: moved.value]


def _create_mock_cookies_db(db_path: Path, rows, db_version: int = 24) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('version', ?)", (str(db_version),))
        conn.execute(
            """
            CREATE TABLE cookies (
                host_key TEXT,
                name TEXT,
                value TEXT,
                encrypted_value BLOB,
                expires_utc INTEGER,
                last_access_utc INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class TestChromeCookies(unittest.TestCase):
    def test_merge_cookies_prioritizes_app_id_and_excludes_other_shops(self):
        cookies = [
            {"domain": ".xiaoeknow.com", "name": "ko_token", "value": "shared_old", "last_access_utc": 100, "profile": "Default"},
            {"domain": "appbbb.h5.xiaoeknow.com", "name": "ko_token", "value": "shop_b_tok", "last_access_utc": 50, "profile": "Profile 1"},
            {"domain": "appaaa.h5.xiaoeknow.com", "name": "ko_token", "value": "shop_a_tok", "last_access_utc": 999, "profile": "Default"},
            {"domain": "appaaa.h5.xiaoeknow.com", "name": "other_only", "value": "should_skip", "last_access_utc": 999, "profile": "Default"},
            {"domain": ".xiaoe-tech.com", "name": "xet_uid", "value": "u123", "last_access_utc": 200, "profile": "Profile 1"},
        ]

        merged, profiles = merge_cookies(cookies, app_id="appBBB")
        self.assertEqual(merged["ko_token"], "shop_b_tok")
        self.assertEqual(merged["xet_uid"], "u123")
        self.assertNotIn("other_only", merged)
        self.assertIn("Profile 1", profiles)

    @unittest.skipUnless(sys.platform == "darwin", "macOS CommonCrypto test")
    def test_extract_multi_profile_and_v24_decryption(self):
        password = "test-chrome-safe-storage-pwd"
        key = _derive_macos_chrome_key(password)
        iv = b" " * 16

        future_utc = int((time.time() + 3600 + _CHROMIUM_EPOCH_OFFSET_SECONDS) * 1_000_000)
        past_utc = int((time.time() - 3600 + _CHROMIUM_EPOCH_OFFSET_SECONDS) * 1_000_000)

        host = "app123.h5.xiaoeknow.com"
        prefix = hashlib.sha256(host.encode("utf-8")).digest()
        enc_v24 = b"v10" + _aes_128_cbc_encrypt_macos(key, iv, prefix + b"valid_token_v24")
        enc_expired = b"v10" + _aes_128_cbc_encrypt_macos(key, iv, prefix + b"expired_token")

        with tempfile.TemporaryDirectory() as tmp:
            chrome_dir = Path(tmp)
            # Default profile has no Xiaoetong cookies
            _create_mock_cookies_db(
                chrome_dir / "Default" / "Cookies",
                [(".example.com", "foo", "bar", b"", 0, 100)],
                db_version=24,
            )
            # Profile 1 has Chrome 130+ v24 encrypted Xiaoetong cookie + expired cookie
            _create_mock_cookies_db(
                chrome_dir / "Profile 1" / "Cookies",
                [
                    (host, "ko_token", "", enc_v24, future_utc, 500),
                    (host, "old_cookie", "", enc_expired, past_utc, 100),
                    (".xiaoeknow.com", "session_xet", "sess_val", b"", 0, 400),
                ],
                db_version=24,
            )

            res = extract_chrome_cookies(
                app_id="app123",
                chrome_dir=chrome_dir,
                keychain_password_provider=lambda: password,
            )

            self.assertTrue(res["success"], res)
            self.assertIn("Profile 1", res["message"])
            self.assertIn("ko_token=valid_token_v24", res["cookie"])
            self.assertIn("session_xet=sess_val", res["cookie"])
            self.assertNotIn("old_cookie", res["cookie"])
            self.assertEqual(res["profiles_checked"], ["Default", "Profile 1"])

    def test_permission_denied_returns_clear_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            chrome_dir = Path(tmp)
            with mock.patch.object(Path, "iterdir", side_effect=PermissionError(1, "Operation not permitted")):
                res = extract_chrome_cookies(chrome_dir=chrome_dir)

            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "permission_denied")
            self.assertIn("完全磁盘访问权限", res["message"])

    def test_keychain_denied_returns_clear_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            chrome_dir = Path(tmp)
            _create_mock_cookies_db(
                chrome_dir / "Default" / "Cookies",
                [(".xiaoeknow.com", "ko_token", "", b"v10" + b"\x00" * 16, 0, 100)],
                db_version=24,
            )

            def fail_keychain():
                raise KeychainAccessError("User interaction is not allowed")

            res = extract_chrome_cookies(
                chrome_dir=chrome_dir,
                keychain_password_provider=fail_keychain,
            )

            self.assertFalse(res["success"])
            self.assertEqual(res["error_code"], "keychain_denied")
            self.assertIn("Chrome Safe Storage", res["message"])


if __name__ == "__main__":
    unittest.main()
