import asyncio
import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
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
                    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            # Убираем легаси-колонку skip, если база создавалась до её удаления.
            cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
            if "skip" in cols:
                conn.execute("DROP INDEX IF EXISTS idx_messages_chat_skip_id")
                conn.execute("ALTER TABLE messages DROP COLUMN skip")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat_id "
                "ON messages (chat_id, id)"
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
                "WHERE chat_id = ? ORDER BY id ASC",
                (chat_id,),
            )
            return cur.fetchall()

    def _clear_history(self, chat_id: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE chat_id = ?",
                (chat_id,),
            )
            return cur.rowcount

    async def add_message(self, chat_id: int, role: str, content: str) -> None:
        await asyncio.to_thread(self._add_message, chat_id, role, content)

    async def get_history(self, chat_id: int) -> list[tuple[str, str]]:
        return await asyncio.to_thread(self._get_history, chat_id)

    async def clear_history(self, chat_id: int) -> int:
        return await asyncio.to_thread(self._clear_history, chat_id)
