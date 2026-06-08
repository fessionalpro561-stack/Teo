#!/usr/bin/env python3
"""
main.py
───────
FER3OON Telegram Channel Sync — Entry Point

Two-phase operation:
  Phase 1 (Archive):   Import all historical messages from source channels.
  Phase 2 (Live):      Monitor source channels for new posts in real time.

Usage:
  python main.py                  — run both phases
  python main.py --archive-only   — only import history, then exit
  python main.py --live-only      — skip archive, jump straight to live mode
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from aiohttp import web

# ── Project imports ───────────────────────────────────────────
import config.settings as cfg
from database import Database
from modules import (
    setup_logger,
    get_logger,
    ContentModifier,
    FER3OONClient,
    Publisher,
    ArchiveImporter,
    LiveWatcher,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="FER3OON Telegram Channel Sync Tool"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--archive-only",
        action="store_true",
        help="Import historical archive then exit (skip live monitoring)",
    )
    mode.add_argument(
        "--live-only",
        action="store_true",
        help="Skip archive import; start live monitoring immediately",
    )
    return parser.parse_args()


async def shutdown(signal_name: str, loop: asyncio.AbstractEventLoop):
    """Graceful shutdown on SIGINT / SIGTERM."""
    logger = get_logger("main")
    logger.info(f"Received {signal_name}. Initiating graceful shutdown…")
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


async def start_keepalive_server():
    """
    HTTP server بسيط على البورت اللي Railway بيحدده.
    بيخلي Railway يشوف الـ service Active ومش بينامها.
    """
    port = int(os.getenv("PORT", "8080"))

    async def health(request):
        return web.Response(text="FER3OON Sync is running ✅")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger = logging.getLogger("fer3oon.keepalive")
    logger.info(f"Keepalive HTTP server running on port {port}")


async def main():
    args = parse_args()

    # ── Keepalive HTTP server (يمنع Railway من تنويم الـ service) ──
    await start_keepalive_server()

    # ── Logging setup ─────────────────────────────────────────
    setup_logger(
        log_level=cfg.LOG_LEVEL,
        log_file=cfg.LOG_FILE,
        max_bytes=cfg.LOG_MAX_BYTES,
        backup_count=cfg.LOG_BACKUP_COUNT,
    )
    logger = get_logger("main")

    # ── Validate config ───────────────────────────────────────
    if not cfg.API_ID or not cfg.API_HASH:
        logger.critical(
            "API_ID or API_HASH is not set!  "
            "Create a .env file or set environment variables.  "
            "See README.md for instructions."
        )
        sys.exit(1)

    if not cfg.SOURCE_CHANNELS or not cfg.DESTINATION_CHANNEL:
        logger.critical("SOURCE_CHANNELS or DESTINATION_CHANNEL is not configured.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("FER3OON Telegram Channel Sync")
    logger.info(f"Sources       : {', '.join(cfg.SOURCE_CHANNELS)}")
    logger.info(f"Destination   : {cfg.DESTINATION_CHANNEL}")
    logger.info(f"Archive only  : {args.archive_only}")
    logger.info(f"Live only     : {args.live_only}")
    logger.info(f"Duplicate chk : {cfg.DUPLICATE_CHECK}")
    logger.info("=" * 60)

    # ── Database ──────────────────────────────────────────────
    db = Database(cfg.DATABASE_PATH)
    await db.connect()

    # ── Telegram client ───────────────────────────────────────
    tg_client = FER3OONClient(
        session_name=cfg.SESSION_NAME,
        api_id=cfg.API_ID,
        api_hash=cfg.API_HASH,
        max_retries=cfg.MAX_RETRIES,
        retry_base_delay=cfg.RETRY_BASE_DELAY,
        floodwait_multiplier=cfg.FLOODWAIT_MULTIPLIER,
    )
    await tg_client.start()

    # ── Content modifier ──────────────────────────────────────
    modifier = ContentModifier(
        footer_text=cfg.FOOTER_TEXT,
        source_signature_patterns=cfg.SOURCE_SIGNATURE_PATTERNS,
        replace_links=cfg.REPLACE_LINKS,
        remove_hashtags=cfg.REMOVE_HASHTAGS,
        replace_hashtags=cfg.REPLACE_HASHTAGS,
        add_hashtags=cfg.ADD_HASHTAGS,
        destination_channel=cfg.DESTINATION_CHANNEL,
        owner_username=cfg.OWNER_USERNAME,
        source_identifiers=cfg.SOURCE_IDENTIFIERS,
        promo_keywords=cfg.PROMO_KEYWORDS,
        gemini_api_key=cfg.GEMINI_API_KEY,
        gemini_model=cfg.GEMINI_MODEL,
    )

    # ── Publisher ─────────────────────────────────────────────
    publisher = Publisher(
        client=tg_client,
        destination_channel=cfg.DESTINATION_CHANNEL,
        post_delay=cfg.POST_DELAY,
    )

    try:
        # ────────────────────────────────────────────────────
        # PHASE 1 — Archive import
        # ────────────────────────────────────────────────────
        live_only = args.live_only or os.getenv("LIVE_ONLY", "false").lower() == "true"

        if not live_only:
            logger.info("▶ Phase 1: Archive import starting…")
            importer = ArchiveImporter(
                client=tg_client,
                db=db,
                modifier=modifier,
                publisher=publisher,
                source_channels=cfg.SOURCE_CHANNELS,
                destination_channel=cfg.DESTINATION_CHANNEL,
                batch_size=cfg.ARCHIVE_BATCH_SIZE,
                batch_delay=cfg.ARCHIVE_BATCH_DELAY,
                duplicate_check=cfg.DUPLICATE_CHECK,
            )
            await importer.run()

            stats = await db.get_stats()
            logger.info(
                f"▶ Archive complete. Stats: "
                f"forwarded={stats['forwarded']} | "
                f"skipped={stats['skipped']} | "
                f"errors={stats['errors']}"
            )

            if args.archive_only:
                logger.info("--archive-only flag set. Exiting after archive.")
                return

        # ────────────────────────────────────────────────────
        # PHASE 2 — Live monitoring
        # ────────────────────────────────────────────────────
        logger.info("▶ Phase 2: Live monitoring starting…")
        watcher = LiveWatcher(
            client=tg_client,
            db=db,
            modifier=modifier,
            publisher=publisher,
            source_channels=cfg.SOURCE_CHANNELS,
            destination_channel=cfg.DESTINATION_CHANNEL,
            duplicate_check=cfg.DUPLICATE_CHECK,
        )
        await watcher.setup()

        # Block until Ctrl-C or SIGTERM
        await tg_client.run_until_disconnected()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Shutting down…")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
    finally:
        await tg_client.stop()
        await db.close()
        logger.info("FER3OON Sync stopped cleanly.")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Register SIGINT / SIGTERM for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(
                    shutdown(s.name, loop)
                ),
            )
        except NotImplementedError:
            # Windows does not support add_signal_handler
            pass

    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
