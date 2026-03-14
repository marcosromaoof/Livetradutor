import ctypes
import os
import sqlite3
import time
from ctypes import wintypes

from live_translator.app_paths import get_secrets_db_path


CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _make_blob(data: bytes) -> tuple[DATA_BLOB, object]:
    if not data:
        return DATA_BLOB(0, None), (ctypes.c_ubyte * 1)()
    buffer = (ctypes.c_ubyte * len(data))(*data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    if not blob.pbData or blob.cbData == 0:
        return b""
    return bytes(ctypes.string_at(blob.pbData, blob.cbData))


def _entropy_blob() -> tuple[DATA_BLOB, object]:
    # App-scoped entropy hardens accidental cross-app decryption.
    return _make_blob(b"LiveTradutor::SecretStore::v1")


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure key storage is supported only on Windows.")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    data_in, data_buffer = _make_blob(data)
    entropy, entropy_buffer = _entropy_blob()
    data_out = DATA_BLOB()

    ok = crypt32.CryptProtectData(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")

    try:
        return _blob_to_bytes(data_out)
    finally:
        kernel32.LocalFree(data_out.pbData)
        _ = data_buffer
        _ = entropy_buffer


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure key storage is supported only on Windows.")

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    data_in, data_buffer = _make_blob(data)
    entropy, entropy_buffer = _entropy_blob()
    data_out = DATA_BLOB()

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(data_in),
        None,
        ctypes.byref(entropy),
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(data_out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")

    try:
        return _blob_to_bytes(data_out)
    finally:
        kernel32.LocalFree(data_out.pbData)
        _ = data_buffer
        _ = entropy_buffer


class SecureSecretStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_secrets_db_path()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        last_exc: Exception | None = None
        for _ in range(3):
            try:
                conn = sqlite3.connect(self.db_path, isolation_level=None)
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("PRAGMA secure_delete=ON")
                conn.execute("PRAGMA synchronous=FULL")
                return conn
            except sqlite3.DatabaseError as exc:
                last_exc = exc
                try:
                    os.remove(self.db_path)
                except Exception:
                    pass
                try:
                    with open(self.db_path, "wb") as handle:
                        handle.truncate(0)
                except Exception:
                    pass
        if last_exc is not None:
            raise last_exc
        # Defensive fallback; should not be reached.
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    name TEXT PRIMARY KEY,
                    encrypted BLOB NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def set_secret(self, name: str, value: str) -> None:
        key = name.strip().lower()
        secret = value.strip()
        if not key:
            return
        if not secret:
            self.delete_secret(key)
            return

        encrypted = _dpapi_protect(secret.encode("utf-8"))
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO secrets (name, encrypted, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    encrypted = excluded.encrypted,
                    updated_at = excluded.updated_at
                """,
                (key, encrypted, now),
            )

    def get_secret(self, name: str) -> str:
        key = name.strip().lower()
        if not key:
            return ""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT encrypted FROM secrets WHERE name = ?",
                (key,),
            ).fetchone()
        if row is None:
            return ""
        encrypted = bytes(row[0])
        if not encrypted:
            return ""
        return _dpapi_unprotect(encrypted).decode("utf-8", errors="ignore").strip()

    def delete_secret(self, name: str) -> None:
        key = name.strip().lower()
        if not key:
            return
        with self._connect() as conn:
            conn.execute("DELETE FROM secrets WHERE name = ?", (key,))
            conn.execute("VACUUM")

    def clear_all(self) -> None:
        if os.path.isfile(self.db_path):
            with self._connect() as conn:
                conn.execute("DELETE FROM secrets")
                conn.execute("VACUUM")

        # Final wipe pass: remove DB and sidecar files.
        for suffix in ("", "-wal", "-shm"):
            path = f"{self.db_path}{suffix}"
            if not os.path.exists(path):
                continue
            try:
                os.remove(path)
            except Exception:
                pass
