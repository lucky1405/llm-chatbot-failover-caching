import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)


def ensure_db_dir():
    db_path = settings.db_path
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)


async def init_db():
    ensure_db_dir()
    db_path = settings.db_path
    logger.info(f"Initializing SQLite database at: {db_path}")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL, -- 'user' or 'assistant'
                content TEXT NOT NULL,
                metadata TEXT, -- JSON string, assistant messages only
                created_at TEXT NOT NULL -- server time, ISO-8601
            );
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);"
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_id ON messages(id);"
        )
        await db.commit()
    logger.info("Database schema initialized successfully.")


async def check_db_health() -> bool:
    try:
        ensure_db_dir()
        async with aiosqlite.connect(settings.db_path) as db:
            cursor = await db.execute("SELECT 1")
            result = await cursor.fetchone()
            return result is not None and result[0] == 1
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


async def session_has_messages(session_id: str) -> bool:
    async with aiosqlite.connect(settings.db_path) as db:
        cursor = await db.execute(
            "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
            (session_id,)
        )
        row = await cursor.fetchone()
        return row is not None


async def get_session_messages_raw(session_id: str) -> List[Dict[str, Any]]:
    """
    Returns messages for a session in chronological order (oldest first).
    """
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT role, content, metadata, created_at FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_session_history_for_llm(session_id: str) -> List[Dict[str, str]]:
    """
    Returns [{'role': 'user'|'assistant', 'content': '...'}] for sending to the LLM.
    """
    rows = await get_session_messages_raw(session_id)
    return [{"role": r["role"], "content": r["content"]} for r in rows]


async def save_message(session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata) if metadata is not None else None
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, meta_json, now_iso)
        )
        await db.commit()


async def save_turn(session_id: str, user_content: str, assistant_content: str, assistant_metadata: Dict[str, Any]):
    """
    Atomically saves both user message and assistant reply to the session history.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(assistant_metadata)
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            """
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "user", user_content, None, now_iso)
        )
        await db.execute(
            """
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, "assistant", assistant_content, meta_json, now_iso)
        )
        await db.commit()
