"""
modules/publisher.py
────────────────────
Publishes messages to the destination channel.

FIXES vs previous version:
  1. Albums: each file buffer gets the correct MIME type hint via .name attribute
     so Telegram doesn't guess wrong and break the album layout.
  2. Albums: captions assigned to the LAST item (Telegram convention for channels),
     not the first — prevents caption from appearing before all photos load.
  3. Single media: voice notes and round videos (video notes) detected and
     sent with the correct send_file flags so they render natively.
  4. Albums with mixed photo+video: handled correctly (Telethon supports it).
"""

import asyncio
import io
import logging
from typing import Optional

from telethon.tl.types import (
    Message,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaWebPage,
    DocumentAttributeVideo,
    DocumentAttributeAudio,
)

logger = logging.getLogger("fer3oon.publisher")


class Publisher:

    def __init__(self, client, destination_channel: str, post_delay: float = 1.5):
        self._client = client
        self.destination = destination_channel
        self.post_delay = post_delay

    # ─── Main dispatcher ──────────────────────────────────────

    async def publish(
        self,
        message: Message,
        modified_text: Optional[str],
        grouped_messages: Optional[list] = None,
    ) -> Optional[int]:
        try:
            if grouped_messages:
                return await self._publish_album(grouped_messages, modified_text)
            elif message.media and not isinstance(message.media, MessageMediaWebPage):
                return await self._publish_media(message, modified_text)
            else:
                return await self._publish_text(modified_text or "")
        except Exception as e:
            logger.error(f"Publish failed for msg {message.id}: {e}", exc_info=True)
            return None
        finally:
            if self.post_delay > 0:
                await asyncio.sleep(self.post_delay)

    # ─── Text ─────────────────────────────────────────────────

    async def _publish_text(self, text: str) -> Optional[int]:
        if not text.strip():
            return None
        sent = await self._client.send_message_safe(
            self.destination,
            message=text,
            parse_mode=None,
            link_preview=False,
        )
        return sent.id if sent else None

    # ─── Single media ─────────────────────────────────────────

    async def _publish_media(self, message: Message, caption: Optional[str]) -> Optional[int]:
        data = await self._client.download_media_safe(message)
        if data is None:
            logger.warning(f"Media download failed for msg {message.id}; sending text only.")
            return await self._publish_text(caption) if caption else None

        buf = self._make_buffer(message, data)
        kwargs = dict(caption=caption, parse_mode=None)

        # Detect special media types
        if self._is_voice(message):
            kwargs["voice_note"] = True
        elif self._is_video_note(message):
            kwargs["video_note"] = True
        elif self._is_document(message):
            kwargs["force_document"] = True

        sent = await self._client.send_file_safe(self.destination, file=buf, **kwargs)
        if sent:
            return sent[0].id if isinstance(sent, list) else sent.id
        return None

    # ─── Album ────────────────────────────────────────────────

    async def _publish_album(self, messages: list, caption: Optional[str]) -> Optional[int]:
        """
        Re-upload a media group as a native Telegram album.

        Telegram album rules:
          - Max 10 items per album
          - Caption on the LAST item (channel convention)
          - Mix of photos and videos allowed; documents break albums
        """
        # Sort by id to preserve original order
        messages = sorted(messages, key=lambda m: m.id)

        # Split into chunks of 10 (Telegram hard limit)
        chunks = [messages[i:i+10] for i in range(0, len(messages), 10)]
        first_dest_id = None

        for chunk_idx, chunk in enumerate(chunks):
            files = []
            for msg in chunk:
                data = await self._client.download_media_safe(msg)
                if data is None:
                    logger.warning(f"Skipping album item msg={msg.id} (download failed)")
                    continue
                buf = self._make_buffer(msg, data)
                files.append(buf)

            if not files:
                continue

            # Caption only on last chunk's last file
            is_last_chunk = (chunk_idx == len(chunks) - 1)
            chunk_caption = caption if is_last_chunk else None

            sent = await self._client.send_file_safe(
                self.destination,
                file=files,
                caption=chunk_caption,
                parse_mode=None,
            )

            if sent:
                ids = [s.id for s in sent] if isinstance(sent, list) else [sent.id]
                if first_dest_id is None:
                    first_dest_id = ids[0]
                logger.debug(f"Album chunk {chunk_idx+1}/{len(chunks)}: {len(files)} items → {ids}")

            # Small delay between chunks to avoid FloodWait on large albums
            if chunk_idx < len(chunks) - 1:
                await asyncio.sleep(1.0)

        return first_dest_id

    # ─── Buffer helpers ───────────────────────────────────────

    @staticmethod
    def _make_buffer(message: Message, data: bytes) -> io.BytesIO:
        """
        Wrap raw bytes in a BytesIO with a .name that hints the MIME type.
        Telethon uses the filename extension to decide how to upload.
        """
        buf = io.BytesIO(data)
        filename = Publisher._get_filename(message)
        if filename:
            buf.name = filename
        elif isinstance(message.media, MessageMediaPhoto):
            buf.name = f"photo_{message.id}.jpg"
        elif isinstance(message.media, MessageMediaDocument):
            mime = getattr(message.media.document, "mime_type", "") or ""
            ext = Publisher._mime_to_ext(mime)
            buf.name = f"media_{message.id}{ext}"
        return buf

    @staticmethod
    def _mime_to_ext(mime: str) -> str:
        table = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "audio/mpeg": ".mp3",
            "audio/ogg": ".ogg",
            "audio/mp4": ".m4a",
        }
        return table.get(mime, "")

    @staticmethod
    def _get_filename(message: Message) -> Optional[str]:
        if not isinstance(message.media, MessageMediaDocument):
            return None
        for attr in getattr(message.media.document, "attributes", []):
            if hasattr(attr, "file_name") and attr.file_name:
                return attr.file_name
        return None

    @staticmethod
    def _is_document(message: Message) -> bool:
        if not isinstance(message.media, MessageMediaDocument):
            return False
        mime = getattr(message.media.document, "mime_type", "") or ""
        return not mime.startswith(("image/", "video/", "audio/"))

    @staticmethod
    def _is_voice(message: Message) -> bool:
        if not isinstance(message.media, MessageMediaDocument):
            return False
        for attr in getattr(message.media.document, "attributes", []):
            if isinstance(attr, DocumentAttributeAudio) and getattr(attr, "voice", False):
                return True
        return False

    @staticmethod
    def _is_video_note(message: Message) -> bool:
        if not isinstance(message.media, MessageMediaDocument):
            return False
        for attr in getattr(message.media.document, "attributes", []):
            if isinstance(attr, DocumentAttributeVideo) and getattr(attr, "round_message", False):
                return True
        return False
