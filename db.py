import asyncio
import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER NOT NULL,
                    role       TEXT    NOT NULL CHECK (role IN ('user', 'model')),
                    content    TEXT    NOT NULL,
                    skip       INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat_skip_id "
                "ON messages (chat_id, skip, id)"
            )

    def _add_message(self, chat_id: int, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                (chat_id, role, content),
            )

    def _get_history(self, chat_id: int) -> list[tuple[str, str]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE chat_id = ? AND skip = 0 ORDER BY id ASC",
                (chat_id,),
            )
            return cur.fetchall()

    def _reset_history(self, chat_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE messages SET skip = 1 "
                "WHERE chat_id = ? AND skip = 0",
                (chat_id,),
            )
            return cur.rowcount

    async def add_message(self, chat_id: int, role: str, content: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._add_message, chat_id, role, content)

    async def get_history(self, chat_id: int) -> list[tuple[str, str]]:
        async with self._lock:
            return await asyncio.to_thread(self._get_history, chat_id)

    async def reset_history(self, chat_id: int) -> int:
        async with self._lock:
            return await asyncio.to_thread(self._reset_history, chat_id)
