"""
modules/live_watcher.py
────────────────────────
Phase 2 — Real-time monitoring.

FIXES vs previous version:
  1. Album buffering: sliding window timer resets on every new item arrival.
  2. Album ordering: sorted by id before publish.
  3. cursor advanced for ALL items in album.
  4. Gap recovery on startup.
  5. Error isolation.
  6. [NEW] Polling fallback every 60s as backup for missed events (large channels).
"""

import asyncio
import logging
from typing import Optional

from telethon import events
from telethon.tl.types import Message, MessageMediaWebPage

from database import Database, compute_hash
from modules.content_modifier import ContentModifier
from modules.publisher import Publisher
from modules.telegram_client import FER3OONClient

logger = logging.getLogger("fer3oon.live")

ALBUM_COLLECT_TIMEOUT = 4.0
POLL_INTERVAL = 60  # seconds


class LiveWatcher:

    def __init__(
        self,
        client: FER3OONClient,
        db: Database,
        modifier: ContentModifier,
        publisher: Publisher,
        source_channels: list[str],
        destination_channel: str,
        duplicate_check: bool = True,
    ):
        self._client = client
        self._db = db
        self._modifier = modifier
        self._publisher = publisher
        self._sources = source_channels
        self._destination = destination_channel
        self._duplicate_check = duplicate_check

        self._pending_albums: dict[int, dict] = {}
        self._lock = asyncio.Lock()
        self._channel_id_map: dict[int, str] = {}
        self._channel_entity_map: dict[str, object] = {}

    # ─── Setup ────────────────────────────────────────────────

    async def setup(self):
        channel_entities = []

        for username in self._sources:
            entity = await self._client.resolve_channel(username)
            if entity is None:
                logger.error(f"[{username}] Cannot resolve — skipping.")
                continue
            self._channel_id_map[entity.id] = username
            self._channel_entity_map[username] = entity
            channel_entities.append(entity)
            logger.info(f"[{username}] Resolved for live monitoring (id={entity.id})")

        if not channel_entities:
            logger.error("No valid channels to monitor!")
            return

        # Gap recovery before registering handler
        for entity in channel_entities:
            username = self._channel_id_map[entity.id]
            await self._recover_gap(entity, username)

        # Register live event handler
        @self._client.client.on(events.NewMessage(chats=channel_entities))
        async def _on_new_message(event: events.NewMessage.Event):
            try:
                await self._handle_new_message(event)
            except Exception as e:
                logger.error(f"Unhandled error in live handler: {e}", exc_info=True)

        # Start polling loop as backup
        asyncio.create_task(self._polling_loop())

        logger.info(
            f"✅ Live watcher active on {len(channel_entities)} channel(s). "
            f"Polling every {POLL_INTERVAL}s as backup."
        )

    # ─── Polling loop (backup for missed events) ───────────────

    async def _polling_loop(self):
        """
        Every POLL_INTERVAL seconds, check each channel for new messages
        that the event handler may have missed (large channels / subscriber accounts).
        """
        await asyncio.sleep(POLL_INTERVAL)  # initial delay — let events handle first burst

        while True:
            try:
                for username, entity in self._channel_entity_map.items():
                    await self._recover_gap(entity, username)
            except Exception as e:
                logger.error(f"Polling loop error: {e}", exc_info=True)

            await asyncio.sleep(POLL_INTERVAL)

    # ─── Gap recovery ─────────────────────────────────────────

    async def _recover_gap(self, entity, username: str):
        last_id = await self._db.get_last_message_id(username)
        if last_id == 0:
            async for message in self._client.client.iter_messages(entity, limit=1):
                if isinstance(message, Message):
                    await self._db.update_last_message_id(username, message.id)
            return

        logger.debug(f"[{username}] Checking for missed messages after id={last_id}…")

        gap_count = 0
        pending_albums: dict[int, list[Message]] = {}

        async for message in self._client.iter_messages(
            entity, min_id=last_id, reverse=True
        ):
            if not isinstance(message, Message):
                continue

            if message.grouped_id:
                pending_albums.setdefault(message.grouped_id, []).append(message)
                gap_count += 1
                continue

            for gid, msgs in list(pending_albums.items()):
                msgs_sorted = sorted(msgs, key=lambda m: m.id)
                ok = await self._process_album(username, msgs_sorted)
                if ok:
                    await self._db.update_last_message_id(username, msgs_sorted[-1].id)
            pending_albums.clear()

            ok = await self._process_single(username, message)
            if ok:
                await self._db.update_last_message_id(username, message.id)
            gap_count += 1

        for gid, msgs in pending_albums.items():
            msgs_sorted = sorted(msgs, key=lambda m: m.id)
            ok = await self._process_album(username, msgs_sorted)
            if ok:
                await self._db.update_last_message_id(username, msgs_sorted[-1].id)

        if gap_count:
            logger.info(f"[{username}] Recovered {gap_count} missed message(s).")

    # ─── Live event handler ───────────────────────────────────

    async def _handle_new_message(self, event: events.NewMessage.Event):
        message: Message = event.message
        username = self._channel_id_map.get(event.chat_id, str(event.chat_id))
        logger.debug(f"[{username}] Live event: msg id={message.id} grouped={message.grouped_id}")

        if message.grouped_id:
            await self._buffer_album_message(username, message)
        else:
            ok = await self._process_single(username, message)
            if ok:
                await self._db.update_last_message_id(username, message.id)

    # ─── Album buffering (sliding window) ─────────────────────

    async def _buffer_album_message(self, username: str, message: Message):
        gid = message.grouped_id

        async with self._lock:
            if gid not in self._pending_albums:
                self._pending_albums[gid] = {
                    "messages": [],
                    "task": None,
                    "username": username,
                }

            self._pending_albums[gid]["messages"].append(message)

            old_task = self._pending_albums[gid]["task"]
            if old_task and not old_task.done():
                old_task.cancel()

            new_task = asyncio.create_task(self._flush_album_after_timeout(gid))
            self._pending_albums[gid]["task"] = new_task

    async def _flush_album_after_timeout(self, grouped_id: int):
        await asyncio.sleep(ALBUM_COLLECT_TIMEOUT)

        async with self._lock:
            data = self._pending_albums.pop(grouped_id, None)

        if not data:
            return

        messages = sorted(data["messages"], key=lambda m: m.id)
        username = data["username"]

        ok = await self._process_album(username, messages)
        if ok:
            await self._db.update_last_message_id(username, messages[-1].id)

    # ─── Single message processor ─────────────────────────────

    async def _process_single(self, username: str, message: Message) -> bool:
        if not message.text and not message.media:
            return False
        if isinstance(getattr(message, "media", None), MessageMediaWebPage) and not message.text:
            return False
        if await self._db.is_message_processed(username, message.id):
            logger.debug(f"[{username}] msg {message.id} already done — skip.")
            return True

        raw_text = message.text or message.message or ""
        content_hash = compute_hash(raw_text)

        if self._duplicate_check and content_hash:
            if await self._db.is_duplicate_hash(content_hash):
                logger.info(f"[LIVE][{username}] Duplicate msg {message.id} — skip.")
                await self._db.mark_message(username, message.id, content_hash, status="skipped")
                return True

        modified_text = await self._modifier.process(raw_text)

        if modified_text is None:
            logger.info(f"[LIVE][{username}] رسالة ترويجية (msg {message.id}) — تم حذفها.")
            await self._db.mark_message(username, message.id, content_hash, status="skipped")
            return True

        dest_id = await self._publisher.publish(message, modified_text)

        status = "forwarded" if dest_id else "error"
        await self._db.mark_message(
            username, message.id, content_hash,
            status=status, destination_msg_id=dest_id,
        )

        if dest_id:
            await self._db.save_hash(content_hash, username, message.id)
            logger.info(f"[LIVE][{username}] ✓ msg {message.id} → dest {dest_id}")
            return True
        else:
            logger.warning(f"[LIVE][{username}] ✗ msg {message.id} failed.")
            return False

    # ─── Album processor ──────────────────────────────────────

    async def _process_album(self, username: str, messages: list[Message]) -> bool:
        if not messages:
            return False

        first = messages[0]

        if await self._db.is_message_processed(username, first.id):
            logger.debug(f"[{username}] album gid={first.grouped_id} already done — skip.")
            return True

        caption_text = next(
            (m.text or m.message for m in messages if m.text or m.message), ""
        )
        content_hash = compute_hash(caption_text + str(first.grouped_id))

        if self._duplicate_check and content_hash:
            if await self._db.is_duplicate_hash(content_hash):
                logger.info(f"[LIVE][{username}] Duplicate album gid={first.grouped_id} — skip.")
                for m in messages:
                    await self._db.mark_message(username, m.id, content_hash, status="skipped")
                return True

        modified_text = await self._modifier.process(caption_text) if caption_text else None

        if caption_text and modified_text is None:
            logger.info(f"[LIVE][{username}] ألبوم ترويجي gid={first.grouped_id} — تم حذفه.")
            for m in messages:
                await self._db.mark_message(username, m.id, content_hash, status="skipped")
            return True

        dest_id = await self._publisher.publish(first, modified_text, grouped_messages=messages)

        status = "forwarded" if dest_id else "error"
        for m in messages:
            await self._db.mark_message(
                username, m.id, content_hash,
                status=status, destination_msg_id=dest_id,
            )

        if dest_id:
            await self._db.save_hash(content_hash, username, first.id)
            logger.info(
                f"[LIVE][{username}] ✓ album gid={first.grouped_id} "
                f"({len(messages)} items) → dest {dest_id}"
            )
            return True
        else:
            logger.warning(f"[LIVE][{username}] ✗ album gid={first.grouped_id} failed.")
            return False
