#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Chrome 浏览器 Cookie 读取与解密工具

在 macOS 上直接扫描所有 Chrome Profile（Default、Profile * 等），
通过临时副本避免 SQLite 文件锁冲突，并使用 macOS 原生 CommonCrypto
解密 v10/v11 Cookie（兼容 Chrome 130+ db_version >= 24 的 32 字节
host_key SHA-256 前缀），同时精准区分 macOS 磁盘权限拦截与钥匙串拒绝。
"""

import ctypes
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


XIAOE_DOMAINS = (
    ".xiaoe-tech.com",
    ".xet.citv.cn",
    ".xiaoeknow.com",
    ".xet.tech",
)

XIAOE_KEYWORDS = ("xiaoe", "xet", "ko_token", "colla_login")

_APP_SUBDOMAIN_RE = re.compile(r"^\.?(app[a-z0-9]+)\.h5\.xiaoeknow\.com$", re.IGNORECASE)

# Chromium timestamps use microseconds since 1601-01-01 00:00:00 UTC
_CHROMIUM_EPOCH_OFFSET_SECONDS = 11644473600

# macOS CommonCrypto constants
_KCC_DECRYPT = 1
_KCC_ALG_AES128 = 0
_KCC_OPT_PKCS7_PADDING = 1


class ChromePermissionError(Exception):
    """macOS TCC / 文件权限拦截导致无法读取 Chrome 数据目录"""


class KeychainAccessError(Exception):
    """无法从 macOS 钥匙串读取 Chrome Safe Storage 密钥"""


def _is_permission_error(err: Exception) -> bool:
    if isinstance(err, (PermissionError, ChromePermissionError)):
        return True
    msg = str(err).lower()
    markers = (
        "operation not permitted",
        "permission denied",
        "unable to open database file",
        "error code 14",
    )
    return any(m in msg for m in markers)


def _is_keychain_error(err: Exception) -> bool:
    if isinstance(err, KeychainAccessError):
        return True
    msg = str(err).lower()
    markers = (
        "keychain",
        "safe storage",
        "user interaction is not allowed",
        "errsecauthfailed",
        "secitem",
        "could not be found in the keychain",
    )
    return any(m in msg for m in markers)


def _derive_macos_chrome_key(password: str) -> bytes:
    """根据 macOS 钥匙串密码派生 Chrome Cookie 的 AES-128 密钥"""
    return hashlib.pbkdf2_hmac(
        "sha1",
        password.encode("utf-8"),
        b"saltysalt",
        1003,
        dklen=16,
    )


def _aes_128_cbc_decrypt_macos(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    """调用 macOS 原生 CommonCrypto (libSystem.B.dylib) 进行 AES-128-CBC 解密"""
    if not ciphertext:
        return b""

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

    out_buf = ctypes.create_string_buffer(len(ciphertext) + 16)
    out_moved = ctypes.c_size_t(0)
    status = lib.CCCrypt(
        _KCC_DECRYPT,
        _KCC_ALG_AES128,
        _KCC_OPT_PKCS7_PADDING,
        key,
        len(key),
        iv,
        ciphertext,
        len(ciphertext),
        out_buf,
        len(out_buf),
        ctypes.byref(out_moved),
    )
    if status != 0:
        raise ValueError(f"CommonCrypto CCCrypt failed with status {status}")
    return out_buf.raw[: out_moved.value]


def _get_macos_chrome_keychain_password() -> str:
    """从 macOS 钥匙串获取 Chrome Safe Storage 密码"""
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-w",
                "-s",
                "Chrome Safe Storage",
                "-a",
                "Chrome",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise KeychainAccessError("等待系统钥匙串授权超时") from exc
    except Exception as exc:
        raise KeychainAccessError(str(exc)) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise KeychainAccessError(stderr or f"security 命令返回错误码 {result.returncode}")

    password = result.stdout.strip()
    if not password:
        raise KeychainAccessError("钥匙串中 Chrome Safe Storage 密钥为空")
    return password


def _decrypt_chrome_cookie_value(
    host_key: str,
    plain_value: str,
    encrypted_value: Optional[bytes],
    db_version: int,
    get_aes_key: Callable[[], bytes],
) -> str:
    """解密单条 Chrome Cookie，兼容明文、v10/v11 以及 Chrome 130+ (db_version >= 24)"""
    if plain_value:
        return plain_value
    if not encrypted_value:
        return ""

    raw = bytes(encrypted_value)
    if raw[:3] in (b"v10", b"v11"):
        key = get_aes_key()
        decrypted = _aes_128_cbc_decrypt_macos(key, b" " * 16, raw[3:])
        expected_hash = hashlib.sha256(host_key.encode("utf-8")).digest()
        if len(decrypted) >= 32 and decrypted[:32] == expected_hash:
            decrypted = decrypted[32:]
        elif db_version >= 24 and len(decrypted) >= 32:
            try:
                decrypted.decode("utf-8")
            except UnicodeDecodeError:
                decrypted = decrypted[32:]
        try:
            return decrypted.decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return ""

    try:
        return raw.decode("utf-8").strip("\x00")
    except UnicodeDecodeError:
        return ""


def _discover_macos_chrome_cookie_dbs(chrome_dir: Path) -> List[Tuple[str, Path]]:
    """发现 Chrome 目录下的全部 Profile Cookies 数据库路径"""
    if not chrome_dir.exists():
        return []

    try:
        entries = list(chrome_dir.iterdir())
    except PermissionError as exc:
        raise ChromePermissionError(f"无法访问 Chrome 目录 {chrome_dir}: {exc}") from exc

    def _sort_key(p: Path) -> Tuple[int, str]:
        name = p.name
        if name == "Default":
            return (0, name)
        m = re.match(r"^Profile (\d+)$", name)
        if m:
            return (1, f"{int(m.group(1)):06d}")
        return (2, name.lower())

    dbs: List[Tuple[str, Path]] = []
    for entry in sorted(entries, key=_sort_key):
        if not entry.is_dir():
            continue
        for rel in ("Cookies", os.path.join("Network", "Cookies")):
            candidate = entry / rel
            try:
                if candidate.is_file():
                    dbs.append((entry.name, candidate))
                    break
            except PermissionError as exc:
                raise ChromePermissionError(f"无法访问 {candidate}: {exc}") from exc

    return dbs


def _read_single_cookie_db(
    profile_name: str,
    db_path: Path,
    get_aes_key: Callable[[], bytes],
) -> List[Dict[str, Any]]:
    """复制并读取单个 Chrome Profile 的 Cookies SQLite 数据库"""
    with tempfile.TemporaryDirectory(prefix="xiaoet_chrome_") as tmp_dir:
        tmp_db = Path(tmp_dir) / "Cookies"
        try:
            shutil.copy2(db_path, tmp_db)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(f"{db_path}{suffix}")
                if sidecar.is_file():
                    try:
                        shutil.copy2(sidecar, Path(f"{tmp_db}{suffix}"))
                    except OSError:
                        pass
        except PermissionError as exc:
            raise ChromePermissionError(f"无法读取 {db_path}: {exc}") from exc

        conn = sqlite3.connect(f"file:{tmp_db}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            db_version = 0
            try:
                row = cursor.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
                if row and row[0] is not None:
                    db_version = int(row[0])
            except sqlite3.Error:
                db_version = 0

            query = """
                SELECT host_key, name, value, encrypted_value, expires_utc, last_access_utc
                FROM cookies
                WHERE LOWER(host_key) LIKE '%xiaoe-tech.com%'
                   OR LOWER(host_key) LIKE '%xet.citv.cn%'
                   OR LOWER(host_key) LIKE '%xiaoeknow.com%'
                   OR LOWER(host_key) LIKE '%xet.tech%'
                   OR LOWER(host_key) LIKE '%xiaoe%'
                   OR LOWER(host_key) LIKE '%xet%'
                   OR LOWER(name) LIKE '%xiaoe%'
                   OR LOWER(name) LIKE '%xet%'
                   OR LOWER(name) LIKE '%ko_token%'
                   OR LOWER(name) LIKE '%colla_login%'
            """
            rows = cursor.execute(query).fetchall()
        finally:
            conn.close()

    now_chromium_utc = int((time.time() + _CHROMIUM_EPOCH_OFFSET_SECONDS) * 1_000_000)
    cookies: List[Dict[str, Any]] = []
    for host_key, name, plain_value, encrypted_value, expires_utc, last_access_utc in rows:
        if not name:
            continue
        # 跳过已明确过期的持久化 Cookie（expires_utc == 0 表示会话 Cookie，保留）
        if (
            isinstance(expires_utc, int)
            and expires_utc > _CHROMIUM_EPOCH_OFFSET_SECONDS * 1_000_000
            and expires_utc < now_chromium_utc
        ):
            continue

        value = _decrypt_chrome_cookie_value(
            host_key=host_key or "",
            plain_value=plain_value or "",
            encrypted_value=encrypted_value,
            db_version=db_version,
            get_aes_key=get_aes_key,
        )
        if not value:
            continue

        cookies.append(
            {
                "domain": host_key or "",
                "name": name,
                "value": value,
                "last_access_utc": int(last_access_utc or 0),
                "profile": profile_name,
            }
        )
    return cookies


def _domain_priority(domain: str, app_id: str) -> Optional[int]:
    """
    计算 Cookie 域名优先级。
    当已知 app_id 时，返回 None 表示该 Cookie 属于其他小鹅通店铺的专属子域名，应排除。
    """
    d = (domain or "").strip().lower()
    aid = (app_id or "").strip().lower()

    if aid:
        target_host = f"{aid}.h5.xiaoeknow.com"
        if d in (target_host, f".{target_host}"):
            return 4
        m = _APP_SUBDOMAIN_RE.match(d)
        if m and m.group(1).lower() != aid:
            return None
        if d in (".h5.xiaoeknow.com", "h5.xiaoeknow.com"):
            return 3
        if d in (".xiaoeknow.com", "xiaoeknow.com"):
            return 2
        if any(d.endswith(dom.lstrip(".")) for dom in XIAOE_DOMAINS):
            return 1
        return 0

    if d.endswith("h5.xiaoeknow.com"):
        return 3
    if d.endswith("xiaoeknow.com"):
        return 2
    if any(d.endswith(dom.lstrip(".")) for dom in XIAOE_DOMAINS):
        return 1
    return 0


def merge_cookies(cookies: List[Dict[str, Any]], app_id: str = "") -> Tuple[Dict[str, str], List[str]]:
    """
    按域名优先级与最近访问时间合并 Cookie，避免旧/其他店铺的同名 Cookie 覆盖有效登录态。

    Returns:
        (merged_cookie_dict, contributing_profiles)
    """
    ranked: List[Tuple[int, int, Dict[str, Any]]] = []
    for c in cookies:
        name = (c.get("name") or "").strip()
        value = c.get("value") or ""
        if not name or not value:
            continue
        prio = _domain_priority(c.get("domain", ""), app_id)
        if prio is None:
            continue
        last_access = int(c.get("last_access_utc") or 0)
        ranked.append((prio, last_access, c))

    # 低优先级 / 较旧的排前面，高优先级 / 较新的排后面覆盖
    ranked.sort(key=lambda item: (item[0], item[1]))

    seen: Dict[str, str] = {}
    profiles_order: List[str] = []
    for _, _, c in ranked:
        seen[c["name"]] = c["value"]
        prof = c.get("profile")
        if prof and prof not in profiles_order:
            profiles_order.append(prof)

    return seen, profiles_order


def _read_with_rookiepy() -> Tuple[List[Dict[str, Any]], List[Exception]]:
    """通过 rookiepy 读取 Chrome Cookie（用于非 macOS 平台）"""
    import rookiepy

    all_cookies: List[Dict[str, Any]] = []
    errors: List[Exception] = []

    for domain in XIAOE_DOMAINS:
        try:
            cookies = rookiepy.chrome([domain])
            all_cookies.extend(cookies)
        except Exception as exc:
            errors.append(exc)

    if not all_cookies:
        try:
            all_browser_cookies = rookiepy.chrome()
            all_cookies = [
                c
                for c in all_browser_cookies
                if any(
                    kw in c.get("domain", "").lower() or kw in c.get("name", "").lower()
                    for kw in XIAOE_KEYWORDS
                )
            ]
        except Exception as exc:
            errors.append(exc)

    return all_cookies, errors


def extract_chrome_cookies(
    app_id: str = "",
    *,
    chrome_dir: Optional[Path] = None,
    keychain_password_provider: Optional[Callable[[], str]] = None,
) -> Dict[str, Any]:
    """
    从 Chrome 浏览器读取小鹅通相关 Cookie。

    Returns:
        {
            "success": bool,
            "message": str,
            "cookie": str,
            "error_code": Optional[str],  # permission_denied | keychain_denied | not_found | error
            "detail": Optional[str],
            "profiles_checked": List[str],
        }
    """
    use_macos_reader = sys.platform == "darwin" or chrome_dir is not None

    if use_macos_reader:
        target_dir = chrome_dir or (
            Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        )
        cached_key: Dict[str, bytes] = {}
        pwd_provider = keychain_password_provider or _get_macos_chrome_keychain_password

        def get_aes_key() -> bytes:
            if "key" not in cached_key:
                cached_key["key"] = _derive_macos_chrome_key(pwd_provider())
            return cached_key["key"]

        try:
            dbs = _discover_macos_chrome_cookie_dbs(target_dir)
        except ChromePermissionError as exc:
            return {
                "success": False,
                "message": (
                    "无法读取 Chrome 数据（macOS 权限受限）。"
                    "请在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中允许本应用（或当前终端），"
                    "重启应用后再试；也可以先展开下方「手动粘贴 Cookie」。"
                ),
                "cookie": "",
                "error_code": "permission_denied",
                "detail": str(exc),
                "profiles_checked": [],
            }

        if not dbs:
            return {
                "success": False,
                "message": "未找到 Chrome 浏览器数据目录，请确认已安装并使用 Chrome 登录小鹅通",
                "cookie": "",
                "error_code": "not_found",
                "detail": f"No Cookies database found under {target_dir}",
                "profiles_checked": [],
            }

        all_cookies: List[Dict[str, Any]] = []
        profiles_checked: List[str] = []
        permission_errors: List[str] = []
        keychain_errors: List[str] = []
        other_errors: List[str] = []

        for profile_name, db_path in dbs:
            profiles_checked.append(profile_name)
            try:
                cookies = _read_single_cookie_db(profile_name, db_path, get_aes_key)
                all_cookies.extend(cookies)
            except ChromePermissionError as exc:
                permission_errors.append(f"{profile_name}: {exc}")
            except KeychainAccessError as exc:
                keychain_errors.append(f"{profile_name}: {exc}")
            except Exception as exc:
                other_errors.append(f"{profile_name}: {exc}")

        if not all_cookies:
            if keychain_errors:
                return {
                    "success": False,
                    "message": (
                        "无法解密 Chrome Cookie（钥匙串未授权）。"
                        "请在系统弹出的「Chrome Safe Storage」授权框中点击「始终允许」，"
                        "或使用下方「手动粘贴 Cookie」。"
                    ),
                    "cookie": "",
                    "error_code": "keychain_denied",
                    "detail": "; ".join(keychain_errors),
                    "profiles_checked": profiles_checked,
                }
            if permission_errors:
                return {
                    "success": False,
                    "message": (
                        "无法读取 Chrome Cookie 文件（macOS 权限受限）。"
                        "请在「系统设置 → 隐私与安全性 → 完全磁盘访问权限」中允许本应用（或当前终端），"
                        "重启应用后再试；也可以先展开下方「手动粘贴 Cookie」。"
                    ),
                    "cookie": "",
                    "error_code": "permission_denied",
                    "detail": "; ".join(permission_errors),
                    "profiles_checked": profiles_checked,
                }
            if other_errors:
                return {
                    "success": False,
                    "message": f"读取 Chrome Cookie 失败：{other_errors[0]}",
                    "cookie": "",
                    "error_code": "error",
                    "detail": "; ".join(other_errors),
                    "profiles_checked": profiles_checked,
                }
            profiles_desc = "、".join(profiles_checked)
            return {
                "success": False,
                "message": (
                    f"已检查 Chrome 配置文件（{profiles_desc}），"
                    "未找到小鹅通登录 Cookie，请确认已在 Chrome 中登录小鹅通"
                ),
                "cookie": "",
                "error_code": "not_found",
                "detail": None,
                "profiles_checked": profiles_checked,
            }

        merged, used_profiles = merge_cookies(all_cookies, app_id=app_id)
        if not merged:
            return {
                "success": False,
                "message": "找到的 Cookie 不属于当前课程所属店铺，请确认在 Chrome 中登录了该课程页面",
                "cookie": "",
                "error_code": "not_found",
                "detail": f"Filtered all cookies for app_id={app_id}",
                "profiles_checked": profiles_checked,
            }

        cookie_str = "; ".join(f"{k}={v}" for k, v in merged.items())
        profile_label = f"（{'、'.join(used_profiles)}）" if used_profiles else ""
        return {
            "success": True,
            "message": f"成功从 Chrome{profile_label}读取 {len(merged)} 个 Cookie",
            "cookie": cookie_str,
            "error_code": None,
            "detail": None,
            "profiles_checked": profiles_checked,
        }

    # 非 macOS 平台走 rookiepy
    try:
        all_cookies, errors = _read_with_rookiepy()
    except Exception as exc:
        return {
            "success": False,
            "message": f"读取 Chrome Cookie 失败: {exc}",
            "cookie": "",
            "error_code": "error",
            "detail": str(exc),
            "profiles_checked": [],
        }

    if not all_cookies:
        if any(_is_keychain_error(e) for e in errors):
            return {
                "success": False,
                "message": "无法解密 Chrome Cookie，请检查系统密钥访问权限或手动粘贴 Cookie",
                "cookie": "",
                "error_code": "keychain_denied",
                "detail": "; ".join(str(e) for e in errors),
                "profiles_checked": [],
            }
        if any(_is_permission_error(e) for e in errors):
            return {
                "success": False,
                "message": "无法打开 Chrome Cookie 文件（可能被权限拦截或被浏览器占用），请完全退出 Chrome 后重试或手动粘贴 Cookie",
                "cookie": "",
                "error_code": "permission_denied",
                "detail": "; ".join(str(e) for e in errors),
                "profiles_checked": [],
            }
        msg = "未找到小鹅通相关 Cookie，请先在 Chrome 中登录小鹅通"
        if errors:
            msg += f"（{errors[0]}）"
        return {
            "success": False,
            "message": msg,
            "cookie": "",
            "error_code": "not_found",
            "detail": "; ".join(str(e) for e in errors) if errors else None,
            "profiles_checked": [],
        }

    merged, _ = merge_cookies(all_cookies, app_id=app_id)
    if not merged:
        return {
            "success": False,
            "message": "找到的 Cookie 不属于当前课程所属店铺，请确认在 Chrome 中登录了该课程页面",
            "cookie": "",
            "error_code": "not_found",
            "detail": f"Filtered all cookies for app_id={app_id}",
            "profiles_checked": [],
        }

    cookie_str = "; ".join(f"{k}={v}" for k, v in merged.items())
    return {
        "success": True,
        "message": f"成功读取 {len(merged)} 个 Cookie",
        "cookie": cookie_str,
        "error_code": None,
        "detail": None,
        "profiles_checked": [],
    }
