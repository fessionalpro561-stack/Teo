"""
database/db.py
─────────────
Unified async database layer — PostgreSQL (production) + SQLite (local dev).

Auto-detection:
  - DATABASE_URL env var set  →  PostgreSQL via asyncpg  (Railway)
  - Not set                   →  SQLite via aiosqlite    (local)

All public methods are identical regardless of backend,
so the rest of the codebase never needs to know which is running.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Backend detection ────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_USE_POSTGRES = bool(DATABASE_URL)


# ══════════════════════════════════════════════════════════════
# PostgreSQL backend  (asyncpg — truly async, Railway-native)
# ══════════════════════════════════════════════════════════════

if _USE_POSTGRES:
    import asyncpg

    class Database:
        """PostgreSQL-backed async database using asyncpg connection pool."""

        def __init__(self, _db_path: str = ""):
            # db_path ignored for Postgres; kept for API compatibility
            self._pool: Optional[asyncpg.Pool] = None

        async def connect(self):
            dsn = DATABASE_URL
            # Railway provides postgres:// but asyncpg needs postgresql://
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql://", 1)

            self._pool = await asyncpg.create_pool(
                dsn,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            await self._create_schema()
            logger.info("PostgreSQL database connected.")

        async def _create_schema(self):
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS channels (
                        id              SERIAL PRIMARY KEY,
                        username        TEXT    UNIQUE NOT NULL,
                        channel_id      BIGINT,
                        title           TEXT,
                        last_message_id BIGINT  DEFAULT 0,
                        archive_done    BOOLEAN DEFAULT FALSE,
                        created_at      TIMESTAMPTZ DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE TABLE IF NOT EXISTS processed_messages (
                        id                 SERIAL PRIMARY KEY,
                        channel_username   TEXT    NOT NULL,
                        message_id         BIGINT  NOT NULL,
                        content_hash       TEXT,
                        status             TEXT    DEFAULT 'forwarded',
                        destination_msg_id BIGINT,
                        processed_at       TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(channel_username, message_id)
                    );

                    CREATE TABLE IF NOT EXISTS content_hashes (
                        hash            TEXT PRIMARY KEY,
                        first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
                        source_channel  TEXT,
                        source_msg_id   BIGINT
                    );

                    CREATE TABLE IF NOT EXISTS sync_logs (
                        id          SERIAL PRIMARY KEY,
                        level       TEXT,
                        event       TEXT,
                        details     JSONB,
                        created_at  TIMESTAMPTZ DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_pm_channel_msg
                        ON processed_messages(channel_username, message_id);

                    CREATE INDEX IF NOT EXISTS idx_pm_hash
                        ON processed_messages(content_hash);
                """)
            logger.info("PostgreSQL schema ready.")

        async def close(self):
            if self._pool:
                await self._pool.close()
                logger.info("PostgreSQL pool closed.")

        # ─── Channel helpers ──────────────────────────────────

        async def upsert_channel(self, username: str, channel_id: int = None, title: str = None):
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO channels (username, channel_id, title)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (username) DO UPDATE SET
                        channel_id = COALESCE(EXCLUDED.channel_id, channels.channel_id),
                        title      = COALESCE(EXCLUDED.title,      channels.title),
                        updated_at = NOW()
                """, username, channel_id, title)

        async def get_channel(self, username: str):
            async with self._pool.acquire() as conn:
                return await conn.fetchrow(
                    "SELECT * FROM channels WHERE username = $1", username
                )

        async def set_archive_done(self, username: str):
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    UPDATE channels SET archive_done = TRUE, updated_at = NOW()
                    WHERE username = $1
                """, username)

        async def update_last_message_id(self, username: str, message_id: int):
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    UPDATE channels
                    SET last_message_id = GREATEST(last_message_id, $1),
                        updated_at = NOW()
                    WHERE username = $2
                """, message_id, username)

        async def get_last_message_id(self, username: str) -> int:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT last_message_id FROM channels WHERE username = $1", username
                )
                return row["last_message_id"] if row else 0

        async def is_archive_done(self, username: str) -> bool:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT archive_done FROM channels WHERE username = $1", username
                )
                return bool(row["archive_done"]) if row else False

        # ─── Message tracking ──────────────────────────────────

        async def is_message_processed(self, channel_username: str, message_id: int) -> bool:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT 1 FROM processed_messages
                    WHERE channel_username = $1 AND message_id = $2
                """, channel_username, message_id)
                return row is not None

        async def mark_message(
            self,
            channel_username: str,
            message_id: int,
            content_hash: str,
            status: str = "forwarded",
            destination_msg_id: int = None,
        ):
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO processed_messages
                        (channel_username, message_id, content_hash, status, destination_msg_id)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (channel_username, message_id) DO NOTHING
                """, channel_username, message_id, content_hash, status, destination_msg_id)

        # ─── Duplicate hash checking ───────────────────────────

        async def is_duplicate_hash(self, content_hash: str) -> bool:
            if not content_hash:
                return False
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM content_hashes WHERE hash = $1", content_hash
                )
                return row is not None

        async def save_hash(self, content_hash: str, source_channel: str, source_msg_id: int):
            if not content_hash:
                return
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO content_hashes (hash, source_channel, source_msg_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (hash) DO NOTHING
                """, content_hash, source_channel, source_msg_id)

        # ─── DB log ────────────────────────────────────────────

        async def log_event(self, level: str, event: str, details: dict = None):
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO sync_logs (level, event, details)
                    VALUES ($1, $2, $3)
                """, level, event, json.dumps(details or {}, ensure_ascii=False))

        # ─── Stats ─────────────────────────────────────────────

        async def get_stats(self) -> dict:
            async with self._pool.acquire() as conn:
                forwarded = await conn.fetchval(
                    "SELECT COUNT(*) FROM processed_messages WHERE status='forwarded'"
                )
                skipped = await conn.fetchval(
                    "SELECT COUNT(*) FROM processed_messages WHERE status='skipped'"
                )
                errors = await conn.fetchval(
                    "SELECT COUNT(*) FROM processed_messages WHERE status='error'"
                )
                channels = await conn.fetch(
                    "SELECT username, archive_done, last_message_id FROM channels"
                )
                return {
                    "forwarded": forwarded,
                    "skipped": skipped,
                    "errors": errors,
                    "channels": [dict(r) for r in channels],
                }


# ══════════════════════════════════════════════════════════════
# SQLite backend  (aiosqlite — local development)
# ══════════════════════════════════════════════════════════════

else:
    import aiosqlite

    class Database:
        """SQLite-backed async database using aiosqlite — for local dev."""

        def __init__(self, db_path: str = "database/sync.db"):
            self.db_path = db_path
            self._conn: Optional[aiosqlite.Connection] = None

        async def connect(self):
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("PRAGMA synchronous=NORMAL")
            await self._create_schema()
            logger.info(f"SQLite database connected: {self.db_path}")

        async def _create_schema(self):
            await self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS channels (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    username        TEXT    UNIQUE NOT NULL,
                    channel_id      INTEGER,
                    title           TEXT,
                    last_message_id INTEGER DEFAULT 0,
                    archive_done    INTEGER DEFAULT 0,
                    created_at      TEXT    DEFAULT (datetime('now')),
                    updated_at      TEXT    DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS processed_messages (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_username   TEXT    NOT NULL,
                    message_id         INTEGER NOT NULL,
                    content_hash       TEXT,
                    status             TEXT    DEFAULT 'forwarded',
                    destination_msg_id INTEGER,
                    processed_at       TEXT    DEFAULT (datetime('now')),
                    UNIQUE(channel_username, message_id)
                );
                CREATE TABLE IF NOT EXISTS content_hashes (
                    hash            TEXT PRIMARY KEY,
                    first_seen_at   TEXT DEFAULT (datetime('now')),
                    source_channel  TEXT,
                    source_msg_id   INTEGER
                );
                CREATE TABLE IF NOT EXISTS sync_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    level      TEXT,
                    event      TEXT,
                    details    TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_pm_channel_msg
                    ON processed_messages(channel_username, message_id);
                CREATE INDEX IF NOT EXISTS idx_pm_hash
                    ON processed_messages(content_hash);
            """)
            await self._conn.commit()
            logger.info("SQLite schema ready.")

        async def close(self):
            if self._conn:
                await self._conn.close()
                logger.info("SQLite connection closed.")

        # ─── Channel helpers ──────────────────────────────────

        async def upsert_channel(self, username: str, channel_id: int = None, title: str = None):
            await self._conn.execute("""
                INSERT INTO channels (username, channel_id, title) VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    channel_id = COALESCE(excluded.channel_id, channel_id),
                    title      = COALESCE(excluded.title, title),
                    updated_at = datetime('now')
            """, (username, channel_id, title))
            await self._conn.commit()

        async def get_channel(self, username: str):
            async with self._conn.execute(
                "SELECT * FROM channels WHERE username = ?", (username,)
            ) as cur:
                return await cur.fetchone()

        async def set_archive_done(self, username: str):
            await self._conn.execute(
                "UPDATE channels SET archive_done=1, updated_at=datetime('now') WHERE username=?",
                (username,)
            )
            await self._conn.commit()

        async def update_last_message_id(self, username: str, message_id: int):
            await self._conn.execute("""
                UPDATE channels
                SET last_message_id = MAX(last_message_id, ?), updated_at = datetime('now')
                WHERE username = ?
            """, (message_id, username))
            await self._conn.commit()

        async def get_last_message_id(self, username: str) -> int:
            async with self._conn.execute(
                "SELECT last_message_id FROM channels WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
                return row["last_message_id"] if row else 0

        async def is_archive_done(self, username: str) -> bool:
            async with self._conn.execute(
                "SELECT archive_done FROM channels WHERE username = ?", (username,)
            ) as cur:
                row = await cur.fetchone()
                return bool(row["archive_done"]) if row else False

        # ─── Message tracking ──────────────────────────────────

        async def is_message_processed(self, channel_username: str, message_id: int) -> bool:
            async with self._conn.execute("""
                SELECT 1 FROM processed_messages
                WHERE channel_username = ? AND message_id = ?
            """, (channel_username, message_id)) as cur:
                return await cur.fetchone() is not None

        async def mark_message(
            self,
            channel_username: str,
            message_id: int,
            content_hash: str,
            status: str = "forwarded",
            destination_msg_id: int = None,
        ):
            await self._conn.execute("""
                INSERT OR IGNORE INTO processed_messages
                    (channel_username, message_id, content_hash, status, destination_msg_id)
                VALUES (?, ?, ?, ?, ?)
            """, (channel_username, message_id, content_hash, status, destination_msg_id))
            await self._conn.commit()

        # ─── Duplicate hash checking ───────────────────────────

        async def is_duplicate_hash(self, content_hash: str) -> bool:
            if not content_hash:
                return False
            async with self._conn.execute(
                "SELECT 1 FROM content_hashes WHERE hash = ?", (content_hash,)
            ) as cur:
                return await cur.fetchone() is not None

        async def save_hash(self, content_hash: str, source_channel: str, source_msg_id: int):
            if not content_hash:
                return
            await self._conn.execute("""
                INSERT OR IGNORE INTO content_hashes (hash, source_channel, source_msg_id)
                VALUES (?, ?, ?)
            """, (content_hash, source_channel, source_msg_id))
            await self._conn.commit()

        # ─── DB log ────────────────────────────────────────────

        async def log_event(self, level: str, event: str, details: dict = None):
            await self._conn.execute("""
                INSERT INTO sync_logs (level, event, details) VALUES (?, ?, ?)
            """, (level, event, json.dumps(details or {}, ensure_ascii=False)))
            await self._conn.commit()

        # ─── Stats ─────────────────────────────────────────────

        async def get_stats(self) -> dict:
            async with self._conn.execute(
                "SELECT COUNT(*) as c FROM processed_messages WHERE status='forwarded'"
            ) as cur:
                forwarded = (await cur.fetchone())["c"]
            async with self._conn.execute(
                "SELECT COUNT(*) as c FROM processed_messages WHERE status='skipped'"
            ) as cur:
                skipped = (await cur.fetchone())["c"]
            async with self._conn.execute(
                "SELECT COUNT(*) as c FROM processed_messages WHERE status='error'"
            ) as cur:
                errors = (await cur.fetchone())["c"]
            async with self._conn.execute(
                "SELECT username, archive_done, last_message_id FROM channels"
            ) as cur:
                channels = await cur.fetchall()
            return {
                "forwarded": forwarded,
                "skipped": skipped,
                "errors": errors,
                "channels": [dict(r) for r in channels],
            }


# ─── Shared utility ───────────────────────────────────────────

def compute_hash(text: str) -> str:
    """Stable SHA-256 hash for duplicate detection."""
    if not text:
        return ""
    normalized = " ".join(text.split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
