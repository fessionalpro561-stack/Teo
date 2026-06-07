"""
modules/telegram_client.py
──────────────────────────
Thin async wrapper around Telethon TelegramClient.
Handles: FloodWait, connection errors, automatic reconnect, retry logic.

Railway / cloud deployment:
  Set STRING_SESSION env var to avoid re-authentication on every redeploy.
  On first local run, the string is printed to console — copy it to Railway.
"""

import asyncio
import logging
import os
from typing import Optional, AsyncGenerator

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    AuthKeyError,
    RPCError,
)
from telethon.sessions import StringSession
from telethon.tl.types import Message, Channel

logger = logging.getLogger("fer3oon.client")


class FER3OONClient:
    """
    Wraps TelegramClient with robust error handling and helpers
    used by both the archive importer and the live watcher.
    """

    def __init__(
        self,
        session_name: str,
        api_id: int,
        api_hash: str,
        max_retries: int = 5,
        retry_base_delay: float = 5.0,
        floodwait_multiplier: float = 1.2,
    ):
        self.session_name = session_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.floodwait_multiplier = floodwait_multiplier

        self._client: Optional[TelegramClient] = None

    # ─── Lifecycle ────────────────────────────────────────────

    async def start(self):
        """
        Connect and authenticate the Telegram client.

        Two modes:
          - STRING_SESSION env var is set  →  use StringSession (Railway/cloud)
          - Not set                        →  use local .session file
        On first local run, prints the StringSession string so you can
        copy it into Railway Variables → STRING_SESSION.
        """
        string_session = os.getenv("STRING_SESSION", "").strip()

        if string_session:
            logger.info("Using StringSession from STRING_SESSION env var.")
            session = StringSession(string_session)
        else:
            logger.info("Using local session file: %s.session", self.session_name)
            session = self.session_name

        self._client = TelegramClient(session, self.api_id, self.api_hash)
        await self._client.start()
        me = await self._client.get_me()
        logger.info(f"Logged in as: {me.first_name} (@{me.username}) [id={me.id}]")

        # Print StringSession on first local login so user can copy to Railway
        if not string_session:
            try:
                ss = StringSession.save(self._client.session)
                logger.info(
                    "\n" + "=" * 60 +
                    "\n📋 STRING_SESSION — copy this value to Railway Variables:\n\n" +
                    ss +
                    "\n\n" + "=" * 60
                )
            except Exception:
                pass

    async def stop(self):
        if self._client and self._client.is_connected():
            await self._client.disconnect()
            logger.info("Telegram client disconnected.")

    @property
    def client(self) -> TelegramClient:
        if not self._client:
            raise RuntimeError("Client not started. Call start() first.")
        return self._client

    # ─── Channel resolution ───────────────────────────────────

    async def resolve_channel(self, username: str) -> Optional[Channel]:
        """Resolve a channel username to a Channel entity."""
        try:
            entity = await self._client.get_entity(username)
            return entity
        except Exception as e:
            logger.error(f"Cannot resolve channel '{username}': {e}")
            return None

    # ─── Message iteration ────────────────────────────────────

    async def iter_messages(
        self,
        channel,
        min_id: int = 0,
        batch_size: int = 100,
        reverse: bool = True,
    ) -> AsyncGenerator[Message, None]:
        """
        Yield messages from *channel* in chronological order.
        min_id: only fetch messages AFTER this ID (exclusive).
        """
        async for msg in self._client.iter_messages(
            channel,
            reverse=reverse,
            min_id=min_id,
            limit=None,
            wait_time=0,
        ):
            yield msg

    # ─── Send helpers ─────────────────────────────────────────

    async def send_message_safe(self, channel, **kwargs) -> Optional[Message]:
        return await self._retry(self._client.send_message, channel, **kwargs)

    async def send_file_safe(self, channel, file, **kwargs) -> Optional[Message]:
        return await self._retry(self._client.send_file, channel, file, **kwargs)

    async def download_media_safe(self, message: Message) -> Optional[bytes]:
        try:
            data = await self._client.download_media(message, bytes)
            return data
        except Exception as e:
            logger.warning(f"Media download failed for msg {message.id}: {e}")
            return None

    # ─── Retry wrapper ────────────────────────────────────────

    async def _retry(self, coro_fn, *args, **kwargs):
        """Exponential backoff with FloodWait awareness."""
        delay = self.retry_base_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                return await coro_fn(*args, **kwargs)
            except FloodWaitError as e:
                wait = int(e.seconds * self.floodwait_multiplier) + 1
                logger.warning(
                    f"FloodWait: sleeping {wait}s "
                    f"(attempt {attempt}/{self.max_retries})"
                )
                await asyncio.sleep(wait)
            except (ConnectionError, OSError) as e:
                logger.warning(
                    f"Connection error (attempt {attempt}/{self.max_retries}): {e}. "
                    f"Retrying in {delay:.1f}s…"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
            except RPCError as e:
                logger.error(f"Telegram RPC error (attempt {attempt}/{self.max_retries}): {e}")
                if attempt == self.max_retries:
                    return None
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                return None

        logger.error(f"All {self.max_retries} attempts failed.")
        return None

    # ─── Event registration ───────────────────────────────────

    def add_event_handler(self, handler, event):
        self._client.add_event_handler(handler, event)

    async def run_until_disconnected(self):
        logger.info("Entering live monitoring mode — running until disconnected…")
        await self._client.run_until_disconnected()
