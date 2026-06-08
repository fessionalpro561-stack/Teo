"""
modules/live_watcher.py
────────────────────────
Phase 2 — Real-time monitoring.

FIXES vs previous version:
  1. Album buffering: sliding window timer resets on every new item arrival,
     so we never flush an incomplete album if Telegram is slow delivering items.
  2. Album ordering: sorted by id before publish (same fix as archive).
  3. cursor (last_message_id) advanced for ALL items in album, not just first.
  4. Gap recovery: on startup, fetch any messages received while bot was down
     (between last_message_id in DB and current latest) before registering handler.
  5. Error isolation: one bad message never crashes the handler loop.
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

# Seconds to wait after the LAST album item before flushing.
# Resets on every new item arrival → handles slow Telegram delivery.
ALBUM_COLLECT_TIMEOUT = 4.0


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

        # grouped_id → {"messages": [], "task": Task, "username": str}
        self._pending_albums: dict[int, dict] = {}
        self._lock = asyncio.Lock()

        # channel_id (int) → username (str)
        self._channel_id_map: dict[int, str] = {}

    # ─── Setup ────────────────────────────────────────────────

    async def setup(self):
        """
        1. Resolve all source channels.
        2. Run gap recovery (messages missed while bot was offline).
        3. Register live event handler.
        """
        channel_entities = []

        for username in self._sources:
            entity = await self._client.resolve_channel(username)
            if entity is None:
                logger.error(f"[{username}] Cannot resolve — skipping.")
                continue
            self._channel_id_map[entity.id] = username
            channel_entities.append(entity)
            logger.info(f"[{username}] Resolved for live monitoring (id={entity.id})")

        if not channel_entities:
            logger.error("No valid channels to monitor!")
            return

        # ── Gap recovery ──────────────────────────────────────
        # Fetch messages that arrived while the bot was offline.
        # This runs BEFORE we register the event handler to avoid duplicates.
        for entity in channel_entities:
            username = self._channel_id_map[entity.id]
            await self._recover_gap(entity, username)

        # ── Register live handler ─────────────────────────────
        @self._client.client.on(events.NewMessage(chats=channel_entities))
        async def _on_new_message(event: events.NewMessage.Event):
            try:
                await self._handle_new_message(event)
            except Exception as e:
                logger.error(f"Unhandled error in live handler: {e}", exc_info=True)

        logger.info(
            f"✅ Live watcher active on {len(channel_entities)} channel(s). "
            "Listening for new posts…"
        )

    # ─── Gap recovery ─────────────────────────────────────────

    async def _recover_gap(self, entity, username: str):
        """
        Fetch and process any messages received since last_message_id.
        Called once at startup before the live handler is registered.
        """
        last_id = await self._db.get_last_message_id(username)
        if last_id == 0:
            # Archive importer handles this case; nothing to recover
            return

        logger.info(f"[{username}] Gap recovery: fetching messages after id={last_id}…")

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

            # Flush completed albums before non-album message
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

        # Flush remaining albums
        for gid, msgs in pending_albums.items():
            msgs_sorted = sorted(msgs, key=lambda m: m.id)
            ok = await self._process_album(username, msgs_sorted)
            if ok:
                await self._db.update_last_message_id(username, msgs_sorted[-1].id)

        if gap_count:
            logger.info(f"[{username}] Gap recovery complete: {gap_count} messages processed.")
        else:
            logger.info(f"[{username}] No gap — channel is up to date.")

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

            # Cancel old timer and start a fresh one (sliding window)
            old_task = self._pending_albums[gid]["task"]
            if old_task and not old_task.done():
                old_task.cancel()

            new_task = asyncio.create_task(self._flush_album_after_timeout(gid))
            self._pending_albums[gid]["task"] = new_task

    async def _flush_album_after_timeout(self, grouped_id: int):
        """Wait, then publish. Cancelled & rescheduled on every new item."""
        await asyncio.sleep(ALBUM_COLLECT_TIMEOUT)

        async with self._lock:
            data = self._pending_albums.pop(grouped_id, None)

        if not data:
            return

        messages = sorted(data["messages"], key=lambda m: m.id)
        username = data["username"]

        ok = await self._process_album(username, messages)
        if ok:
            # Advance cursor to the LAST item in the album
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

        # رسالة ترويجية — تجاهل
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

        # ألبوم ترويجي — تجاهل
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
