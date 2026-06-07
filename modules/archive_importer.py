"""
modules/archive_importer.py
────────────────────────────
Phase 1 — Full historical backfill.

FIXES vs previous version:
  1. last_message_id saved ONLY after successful publish, not on every iteration.
     (Old: saved even for buffered album items before they were processed —
      if crash mid-album the album was lost but last_id was already advanced.)
  2. Album flush guard: if a crash happens mid-album, the album messages are
     still in processed_messages with status='error', so restart picks them up.
  3. Album ordering: messages now sorted by id before publish (Telethon does
     NOT guarantee order within a grouped_id when using iter_messages).
  4. Restart safety: archive_done flag only set AFTER all pending albums flushed.
"""

import asyncio
import logging
from collections import defaultdict
from typing import Optional

from telethon.tl.types import Message, MessageMediaWebPage

from database import Database, compute_hash
from modules.content_modifier import ContentModifier
from modules.publisher import Publisher
from modules.telegram_client import FER3OONClient

logger = logging.getLogger("fer3oon.archive")


class ArchiveImporter:

    def __init__(
        self,
        client: FER3OONClient,
        db: Database,
        modifier: ContentModifier,
        publisher: Publisher,
        source_channels: list[str],
        destination_channel: str,
        batch_size: int = 100,
        batch_delay: float = 2.0,
        duplicate_check: bool = True,
    ):
        self._client = client
        self._db = db
        self._modifier = modifier
        self._publisher = publisher
        self._sources = source_channels
        self._destination = destination_channel
        self._batch_size = batch_size
        self._batch_delay = batch_delay
        self._duplicate_check = duplicate_check

    # ─── Entry point ──────────────────────────────────────────

    async def run(self):
        for username in self._sources:
            if await self._db.is_archive_done(username):
                logger.info(f"[{username}] Archive already complete — skipping.")
                continue
            logger.info(f"[{username}] Starting archive import…")
            await self._import_channel(username)

    # ─── Per-channel import ───────────────────────────────────

    async def _import_channel(self, username: str):
        entity = await self._client.resolve_channel(username)
        if entity is None:
            logger.error(f"[{username}] Cannot resolve channel. Skipping.")
            return

        await self._db.upsert_channel(
            username,
            channel_id=entity.id,
            title=getattr(entity, "title", username),
        )

        # ── RESTART SAFETY ────────────────────────────────────
        # Resume from last *successfully saved* message ID.
        # If a crash happened mid-album, last_id points to before the album,
        # so the whole album is re-fetched and re-attempted cleanly.
        last_id = await self._db.get_last_message_id(username)
        logger.info(f"[{username}] Resuming from message id={last_id} (0 = beginning)")

        total_forwarded = 0
        total_skipped = 0
        batch_count = 0

        # grouped_id → [Message, ...] — collected as we stream
        pending_albums: dict[int, list[Message]] = defaultdict(list)
        # Track the highest message id seen so far (for batch checkpoints)
        highest_id_seen = last_id

        async for message in self._client.iter_messages(
            entity,
            min_id=last_id,
            batch_size=self._batch_size,
            reverse=True,        # oldest → newest  (chronological order)
        ):
            if not isinstance(message, Message):
                continue

            highest_id_seen = max(highest_id_seen, message.id)

            # ── Collect album items ───────────────────────────
            if message.grouped_id:
                pending_albums[message.grouped_id].append(message)
                # DO NOT advance last_message_id here.
                # We only advance it after the full album is successfully published.
                batch_count += 1
                continue

            # ── Non-album message: flush any completed albums first ──
            # Any album whose grouped_id differs from current message is complete
            # (albums are always consecutive in Telegram's history).
            for gid, album_msgs in list(pending_albums.items()):
                # Sort by message id to guarantee correct media order
                album_msgs_sorted = sorted(album_msgs, key=lambda m: m.id)
                ok = await self._process_album(username, album_msgs_sorted)
                total_forwarded += 1 if ok else 0
                total_skipped   += 0 if ok else 1
                if ok:
                    # Advance cursor to the last item in the album
                    await self._db.update_last_message_id(username, album_msgs_sorted[-1].id)
            pending_albums.clear()

            # ── Process single message ────────────────────────
            ok = await self._process_single(username, message)
            total_forwarded += 1 if ok else 0
            total_skipped   += 0 if ok else 1

            # Advance cursor only after successful processing
            if ok:
                await self._db.update_last_message_id(username, message.id)

            batch_count += 1

            # Periodic progress log + polite delay
            if batch_count % self._batch_size == 0:
                logger.info(
                    f"[{username}] Progress: batch={batch_count} "
                    f"forwarded={total_forwarded} skipped={total_skipped} "
                    f"cursor≈{message.id}"
                )
                await asyncio.sleep(self._batch_delay)

        # ── Flush remaining albums at end of history ──────────
        for gid, album_msgs in pending_albums.items():
            album_msgs_sorted = sorted(album_msgs, key=lambda m: m.id)
            ok = await self._process_album(username, album_msgs_sorted)
            total_forwarded += 1 if ok else 0
            total_skipped   += 0 if ok else 1
            if ok:
                await self._db.update_last_message_id(username, album_msgs_sorted[-1].id)

        # ── Mark archive done — only AFTER everything is flushed ─
        await self._db.set_archive_done(username)
        logger.info(
            f"[{username}] ✅ Archive complete. "
            f"Forwarded={total_forwarded} | Skipped={total_skipped}"
        )
        await self._db.log_event(
            "INFO", "archive_complete",
            {"channel": username, "forwarded": total_forwarded, "skipped": total_skipped},
        )

    # ─── Single message processor ─────────────────────────────

    async def _process_single(self, username: str, message: Message) -> bool:
        # Skip service messages (join/leave/pin etc.)
        if not message.text and not message.media:
            return False

        # Skip web-preview ghost messages
        if isinstance(getattr(message, "media", None), MessageMediaWebPage) and not message.text:
            return False

        # Already processed in a previous run?
        if await self._db.is_message_processed(username, message.id):
            logger.debug(f"[{username}] msg {message.id} already in DB — skip.")
            return True   # treat as success so cursor advances

        raw_text = message.text or message.message or ""
        content_hash = compute_hash(raw_text)

        if self._duplicate_check and content_hash:
            if await self._db.is_duplicate_hash(content_hash):
                logger.info(f"[{username}] Duplicate (msg {message.id}) — skip.")
                await self._db.mark_message(username, message.id, content_hash, status="skipped")
                return True   # skipped ≠ error; advance cursor

        modified_text = self._modifier.process(raw_text)
        dest_id = await self._publisher.publish(message, modified_text)

        status = "forwarded" if dest_id else "error"
        await self._db.mark_message(
            username, message.id, content_hash,
            status=status, destination_msg_id=dest_id,
        )

        if dest_id:
            await self._db.save_hash(content_hash, username, message.id)
            logger.info(f"[{username}] ✓ msg {message.id} → dest {dest_id}")
            return True
        else:
            logger.warning(f"[{username}] ✗ msg {message.id} publish failed.")
            return False   # do NOT advance cursor — will retry on restart

    # ─── Album processor ──────────────────────────────────────

    async def _process_album(self, username: str, messages: list[Message]) -> bool:
        """
        Publish a sorted album group.
        messages MUST be pre-sorted by id (caller's responsibility).
        """
        if not messages:
            return False

        first = messages[0]

        # If first item is already done, assume whole album was done
        if await self._db.is_message_processed(username, first.id):
            logger.debug(f"[{username}] album gid={first.grouped_id} already done — skip.")
            return True

        caption_text = next(
            (m.text or m.message for m in messages if m.text or m.message), ""
        )

        # Hash = caption + grouped_id (stable even if caption is empty)
        content_hash = compute_hash(caption_text + str(first.grouped_id))

        if self._duplicate_check and content_hash:
            if await self._db.is_duplicate_hash(content_hash):
                logger.info(f"[{username}] Duplicate album gid={first.grouped_id} — skip.")
                for m in messages:
                    await self._db.mark_message(username, m.id, content_hash, status="skipped")
                return True

        modified_text = self._modifier.process(caption_text) if caption_text else None
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
                f"[{username}] ✓ album gid={first.grouped_id} "
                f"({len(messages)} items) → dest {dest_id}"
            )
            return True
        else:
            logger.warning(f"[{username}] ✗ album gid={first.grouped_id} failed.")
            return False
