import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    async def connect(self):
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        c = self._conn
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                join_date       TEXT NOT NULL,
                total_compressed INTEGER DEFAULT 0,
                total_saved_size INTEGER DEFAULT 0,
                banned          INTEGER DEFAULT 0,
                last_used       TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                file_name       TEXT,
                original_size   INTEGER,
                compressed_size INTEGER,
                saved_size      INTEGER,
                time_taken      REAL,
                quality         TEXT,
                resolution      TEXT,
                timestamp       TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        c.commit()

    async def close(self):
        if self._conn:
            self._conn.close()

    async def get_setting(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    async def set_setting(self, key: str, value: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

    async def del_setting(self, key: str):
        self._conn.execute("DELETE FROM settings WHERE key=?", (key,))
        self._conn.commit()

    async def all_settings(self) -> dict:
        rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    async def get_daily_count(self, user_id: int) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) FROM history WHERE user_id=? AND timestamp LIKE ?",
            (user_id, f"{today}%"),
        ).fetchone()
        return row[0] if row else 0

    async def add_user(self, user_id: int, username: str = "", first_name: str = "") -> bool:
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username, first_name, join_date) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, now),
            )
            self._conn.execute(
                "UPDATE users SET username=?, first_name=?, last_used=? WHERE user_id=?",
                (username, first_name, now, user_id),
            )
            self._conn.commit()
            return True
        except Exception:
            return False

    async def get_user(self, user_id: int) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    async def is_banned(self, user_id: int) -> bool:
        row = self._conn.execute("SELECT banned FROM users WHERE user_id=?", (user_id,)).fetchone()
        return bool(row and row["banned"])

    async def ban_user(self, user_id: int):
        self._conn.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
        self._conn.commit()

    async def unban_user(self, user_id: int):
        self._conn.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
        self._conn.commit()

    async def banned_list(self) -> list[dict]:
        rows = self._conn.execute("SELECT user_id, username, first_name FROM users WHERE banned=1").fetchall()
        return [dict(r) for r in rows]

    async def total_users(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    async def all_user_ids(self) -> list[int]:
        return [r[0] for r in self._conn.execute("SELECT user_id FROM users WHERE banned=0").fetchall()]

    async def record_compression(
        self,
        user_id: int,
        file_name: str,
        original_size: int,
        compressed_size: int,
        saved_size: int,
        time_taken: float,
        quality: str,
        resolution: str,
    ):
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO history (user_id, file_name, original_size, compressed_size, saved_size, time_taken, quality, resolution, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, file_name, original_size, compressed_size, saved_size, time_taken, quality, resolution, now),
        )
        self._conn.execute(
            "UPDATE users SET total_compressed = total_compressed + 1, total_saved_size = total_saved_size + ? WHERE user_id = ?",
            (saved_size, user_id),
        )
        self._conn.commit()

    async def get_history(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT file_name, original_size, compressed_size, saved_size, time_taken, quality, resolution, timestamp FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    async def total_compressions(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    async def total_saved_size_global(self) -> int:
        val = self._conn.execute("SELECT COALESCE(SUM(saved_size), 0) FROM history").fetchone()[0]
        return int(val)

    async def global_stats(self) -> dict:
        users = await self.total_users()
        compressions = await self.total_compressions()
        saved = await self.total_saved_size_global()
        return {"users": users, "compressions": compressions, "total_saved": saved}

    async def top_users(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT user_id, username, first_name, total_compressed, total_saved_size FROM users ORDER BY total_compressed DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    async def today_stats(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(saved_size),0) as saved FROM history WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return {"count": row["cnt"], "saved": row["saved"]}


db = Database(Path(__file__).parent / "bot.db")
