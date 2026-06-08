# ============================================================
# FER3OON Telegram Channel Sync — Configuration File
# ============================================================

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Telegram API Credentials ───────────────────────────────
API_ID   = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_NAME = os.getenv("SESSION_NAME", "fer3oon_sync_session")

# ─── Channel Configuration ───────────────────────────────────
# قنوات المصدر — مكتوبة مباشرة
SOURCE_CHANNELS = ["ForexBreakingNews", "fforexNews", "forexfactory_arabic"]

# القناة المستهدفة — مكتوبة مباشرة
DESTINATION_CHANNEL = os.getenv("DESTINATION_CHANNEL", "ForexNewsEgy")

# ─── Gemini AI ───────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6Irum-mHvqB53YSJuvb4SGzkC5XYVw33JuG8vcKrVCLUQ")
GEMINI_MODEL   = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# ─── Archive / Live ──────────────────────────────────────────
ARCHIVE_BATCH_SIZE  = int(os.getenv("ARCHIVE_BATCH_SIZE", "100"))
ARCHIVE_BATCH_DELAY = float(os.getenv("ARCHIVE_BATCH_DELAY", "2.0"))

# ─── Timing ──────────────────────────────────────────────────
POST_DELAY = float(os.getenv("POST_DELAY", "1.5"))

# ─── Footer / توقيع القناة ───────────────────────────────────
FOOTER_TEXT = os.getenv(
    "FOOTER_TEXT",
    "⬤ قناة أَخبار الفوركس العاجلة 🌎\nhttps://t.me/ForexNewsEgy ✅"
)

# ─── المعرف الشخصي البديل ────────────────────────────────────
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "@X_T_RA_DE_R")

# ─── روابط ومعرفات القنوات المصدر التي يجب استبدالها ─────────
# أي رابط أو يوزرنيم لهذه القنوات يُستبدل برابط قناتنا أو OWNER_USERNAME
SOURCE_IDENTIFIERS = [
    # ForexBreakingNews
    "https://t.me/ForexBreakingNews",
    "http://t.me/ForexBreakingNews",
    "t.me/ForexBreakingNews",
    "Telegram.me/ForexBreakingNews",
    "@ForexBreakingNews",
    "ForexBreakingNews",
    # fforexNews
    "https://t.me/fforexNews",
    "http://t.me/fforexNews",
    "t.me/fforexNews",
    "Telegram.me/fforexNews",
    "@fforexNews",
    "fforexNews",
    # forexfactory_arabic
    "https://t.me/forexfactory_arabic",
    "http://t.me/forexfactory_arabic",
    "t.me/forexfactory_arabic",
    "Telegram.me/forexfactory_arabic",
    "@forexfactory_arabic",
    "forexfactory_arabic",
]

# استبدال الروابط برابط القناة الجديدة
REPLACE_LINKS = {
    "https://t.me/ForexBreakingNews": "https://t.me/ForexNewsEgy",
    "http://t.me/ForexBreakingNews":  "https://t.me/ForexNewsEgy",
    "t.me/ForexBreakingNews":         "t.me/ForexNewsEgy",
    "Telegram.me/ForexBreakingNews":  "https://t.me/ForexNewsEgy",
    "https://t.me/fforexNews":        "https://t.me/ForexNewsEgy",
    "http://t.me/fforexNews":         "https://t.me/ForexNewsEgy",
    "t.me/fforexNews":                "t.me/ForexNewsEgy",
    "Telegram.me/fforexNews":         "https://t.me/ForexNewsEgy",
    "https://t.me/forexfactory_arabic": "https://t.me/ForexNewsEgy",
    "http://t.me/forexfactory_arabic":  "https://t.me/ForexNewsEgy",
    "t.me/forexfactory_arabic":         "t.me/ForexNewsEgy",
    "Telegram.me/forexfactory_arabic":  "https://t.me/ForexNewsEgy",
}

# ─── كلمات الترويج المحظورة ──────────────────────────────────
# أي رسالة تحتوي على أي من هذه العبارات تُحذف ولا تُنشر
PROMO_KEYWORDS = [
    "للتسجيل",
    "للإنضمام",
    "للانضمام",
    "افتح حساب",
    "فتح حساب",
    "انضم مجانا",
    "انضم مجاناً",
    "سجل الان",
    "سجل الآن",
    "اشترك الان",
    "اشترك الآن",
    "تسجيل مجاني",
    "تسجيل مجانى",
    "انضم الآن",
    "انضم الان",
    "احصل على",
    "احصل علي",
    "مكافأة",
    "بونص",
    "bonus",
    "register now",
    "open account",
    "sign up",
    "join now",
    "free registration",
]

# ─── Signature patterns للكشف عن توقيع المصدر ───────────────
SOURCE_SIGNATURE_PATTERNS = [
    r"(?:https?://)?(?:Telegram\.me|t\.me)/ForexBreakingNews[^\n]*",
    r"(?:https?://)?(?:Telegram\.me|t\.me)/fforexNews[^\n]*",
    r"(?:https?://)?(?:Telegram\.me|t\.me)/forexfactory_arabic[^\n]*",
    r"@ForexBreakingNews",
    r"@fforexNews",
    r"@forexfactory_arabic",
]

# ─── Hashtags ────────────────────────────────────────────────
REMOVE_HASHTAGS  = [h.strip().lstrip("#") for h in os.getenv("REMOVE_HASHTAGS", "").split(",") if h.strip()]
REPLACE_HASHTAGS = {}
ADD_HASHTAGS     = [h.strip().lstrip("#") for h in os.getenv("ADD_HASHTAGS", "").split(",") if h.strip()]

# ─── Duplicate check ─────────────────────────────────────────
DUPLICATE_CHECK = os.getenv("DUPLICATE_CHECK", "true").lower() == "true"

# ─── Database ────────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "database/sync.db")

# ─── Logging ─────────────────────────────────────────────────
LOG_LEVEL        = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE         = os.getenv("LOG_FILE", "logs/sync.log")
LOG_MAX_BYTES    = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# ─── Retry ───────────────────────────────────────────────────
MAX_RETRIES          = int(os.getenv("MAX_RETRIES", "5"))
RETRY_BASE_DELAY     = float(os.getenv("RETRY_BASE_DELAY", "5.0"))
FLOODWAIT_MULTIPLIER = float(os.getenv("FLOODWAIT_MULTIPLIER", "1.2"))
