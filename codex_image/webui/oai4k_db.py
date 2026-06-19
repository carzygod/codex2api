from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("output") / "oai4k.db"


class OAI4KDatabase:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS oai4k_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token TEXT DEFAULT '',
                    account_id TEXT DEFAULT '',
                    token_preview TEXT NOT NULL,
                    status TEXT DEFAULT 'unknown',
                    last_check INTEGER,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    api_key TEXT UNIQUE NOT NULL,
                    key_preview TEXT NOT NULL,
                    account_id INTEGER,
                    is_active INTEGER DEFAULT 1,
                    call_count INTEGER DEFAULT 0,
                    last_used INTEGER,
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (account_id) REFERENCES oai4k_accounts(id)
                );

                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt TEXT,
                    key_preview TEXT,
                    size TEXT,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_oai4k_accounts_status ON oai4k_accounts(status);
                CREATE INDEX IF NOT EXISTS idx_api_keys_api_key ON api_keys(api_key);
                CREATE INDEX IF NOT EXISTS idx_media_created_at ON media(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs(created_at DESC);
                """
            )

    @staticmethod
    def _now() -> int:
        return int(time.time())

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def preview(secret: str) -> str:
        clean = str(secret or "")
        if len(clean) <= 10:
            return clean[:3] + "****" if clean else ""
        return f"{clean[:6]}****{clean[-4:]}"

    def is_setup_complete(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            return bool(row and row["count"])

    def create_user(self, username: str, password: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, self.hash_password(password), self._now()),
            )

    def validate_user(self, username: str, password: str) -> int | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, password_hash FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row and row["password_hash"] == self.hash_password(password):
            return int(row["id"])
        return None

    def change_password(self, user_id: int, password: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (self.hash_password(password), user_id),
            )

    def create_session(self, user_id: int) -> str:
        session_id = secrets.token_hex(32)
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (session_id, user_id, now + 24 * 60 * 60, now),
            )
        return session_id

    def validate_session(self, session_id: str) -> int | None:
        now = self._now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            if int(row["expires_at"]) <= now:
                conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                return None
            return int(row["user_id"])

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def add_account(self, name: str, access_token: str, refresh_token: str = "", account_id: str = "") -> int:
        now = self._now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO oai4k_accounts
                  (name, access_token, refresh_token, account_id, token_preview, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, access_token, refresh_token, account_id, self.preview(access_token), now),
            )
            return int(cursor.lastrowid)

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, token_preview, account_id, status, last_check, created_at
                FROM oai4k_accounts
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_account(self, account_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM oai4k_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_account_status(self, account_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE oai4k_accounts SET status = ?, last_check = ? WHERE id = ?",
                (status, self._now(), account_id),
            )

    def delete_account(self, account_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM api_keys WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM oai4k_accounts WHERE id = ?", (account_id,))

    def random_account(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM oai4k_accounts
                WHERE status != 'invalid'
                ORDER BY RANDOM()
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def generate_api_key(self, name: str, account_id: int | None = None) -> str:
        api_key = "sk-oai4k-" + secrets.token_hex(32)
        now = self._now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (name, api_key, key_preview, account_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, api_key, self.preview(api_key), account_id, now),
            )
        return api_key

    def list_api_keys(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT k.id, k.name, k.key_preview, k.account_id, k.is_active, k.call_count,
                       k.last_used, k.created_at, a.name AS account_name
                FROM api_keys k
                LEFT JOIN oai4k_accounts a ON a.id = k.account_id
                ORDER BY k.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def validate_api_key(self, api_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE api_key = ? AND is_active = 1",
                (api_key,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE api_keys SET call_count = call_count + 1, last_used = ? WHERE id = ?",
                (self._now(), row["id"]),
            )
        return dict(row)

    def toggle_api_key(self, key_id: int, is_active: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE api_keys SET is_active = ? WHERE id = ?",
                (1 if is_active else 0, key_id),
            )

    def delete_api_key(self, key_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))

    def save_media(self, media_type: str, url: str, model: str, prompt: str, token: str, size: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO media (type, url, model, prompt, key_preview, size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (media_type, url, model, prompt, self.preview(token), size, self._now()),
            )

    def list_media(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM media ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            accounts = conn.execute("SELECT COUNT(*) AS count FROM oai4k_accounts").fetchone()["count"]
            keys = conn.execute("SELECT COUNT(*) AS count FROM api_keys").fetchone()["count"]
            calls = conn.execute("SELECT COALESCE(SUM(call_count), 0) AS count FROM api_keys").fetchone()["count"]
            media = conn.execute("SELECT COUNT(*) AS count FROM media").fetchone()["count"]
        return {"totals": {"accounts": accounts, "api_keys": keys, "calls": calls, "media": media}}

    def add_log(self, level: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO logs (level, message, created_at) VALUES (?, ?, ?)",
                (level, message, self._now()),
            )
            conn.execute(
                "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT 1000)"
            )

    def list_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
