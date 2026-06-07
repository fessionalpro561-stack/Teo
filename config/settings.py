# ============================================================
# FER3OON Telegram Channel Sync - Configuration File
# ============================================================
# Edit this file to customize behavior. Never edit main.py.
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram API Credentials ───────────────────────────────
# Get from https://my.telegram.org/apps
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "fer3oon_sync_session")

# ─── Channel Configuration ───────────────────────────────────
# Source channels: list of usernames or channel IDs (without @)
SOURCE_CHANNELS = os.getenv(
    "SOURCE_CHANNELS",
    "ForexBreakingNews"
).split(",")

# Strip whitespace from channel names
SOURCE_CHANNELS = [ch.strip() for ch in SOURCE_CHANNELS]

# Destination channel username (without @)
DESTINATION_CHANNEL = os.getenv("DESTINATION_CHANNEL", "FOREX_NEWS_EGY")

# ─── Archive Import Settings ─────────────────────────────────
# How many messages to fetch per batch during archive import
ARCHIVE_BATCH_SIZE = int(os.getenv("ARCHIVE_BATCH_SIZE", "100"))

# Delay (seconds) between batches to avoid FloodWait
ARCHIVE_BATCH_DELAY = float(os.getenv("ARCHIVE_BATCH_DELAY", "2.0"))

# ─── Live Mode Settings ──────────────────────────────────────
# Delay (seconds) between publishing consecutive posts
POST_DELAY = float(os.getenv("POST_DELAY", "1.5"))

# ─── Content Modification Rules ──────────────────────────────

# Footer to append if none exists in the original post
FOOTER_TEXT = os.getenv(
    "FOOTER_TEXT",
    "⬤ قناة أَخبار الفوركس العاجلة 🌎\nhttps://t.me/FOREX_NEWS_EGY ✅"
)

# Patterns of source channel signatures to detect and replace
# These are matched (case-insensitive) and replaced with FOOTER_TEXT
SOURCE_SIGNATURE_PATTERNS = [
    r"(?:Telegram\.me|t\.me|telegram\.me)/ForexBreakingNews\s*✅?",
    r"قناة\s+أَخبار\s+الفوركس\s+العاجلة.*?(?:Telegram\.me|t\.me|https?://t\.me)/ForexBreakingNews[^\n]*",
    r"@ForexBreakingNews",
    r"ForexBreakingNews",
]

# Direct link replacements: map old link → new link
REPLACE_LINKS = {
    "https://t.me/ForexBreakingNews": "https://t.me/FOREX_NEWS_EGY",
    "http://t.me/ForexBreakingNews": "https://t.me/FOREX_NEWS_EGY",
    "Telegram.me/ForexBreakingNews": "https://t.me/FOREX_NEWS_EGY",
    "t.me/ForexBreakingNews": "t.me/FOREX_NEWS_EGY",
}

# ─── Hashtag Rules ───────────────────────────────────────────
# Hashtags to completely remove from posts
REMOVE_HASHTAGS = os.getenv("REMOVE_HASHTAGS", "").split(",")
REMOVE_HASHTAGS = [h.strip().lstrip("#") for h in REMOVE_HASHTAGS if h.strip()]

# Hashtags to replace: {"old": "new"}
REPLACE_HASHTAGS = {
    # "forex": "FOREX_EGY",
}

# Hashtags to add at the end of every post
ADD_HASHTAGS = os.getenv("ADD_HASHTAGS", "").split(",")
ADD_HASHTAGS = [h.strip().lstrip("#") for h in ADD_HASHTAGS if h.strip()]

# ─── Duplicate Prevention ─────────────────────────────────────
# Enable/disable duplicate checking via content hash
DUPLICATE_CHECK = os.getenv("DUPLICATE_CHECK", "true").lower() == "true"

# ─── Database ────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/sync.db")

# ─── Logging ─────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "logs/sync.log")
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# ─── Retry / Error Handling ──────────────────────────────────
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", "5.0"))  # seconds
FLOODWAIT_MULTIPLIER = float(os.getenv("FLOODWAIT_MULTIPLIER", "1.2"))
