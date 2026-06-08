"""
modules/content_modifier.py
────────────────────────────
تعديل المحتوى قبل النشر:
  1. فلترة رسائل الترويج (لا تُنشر)
  2. استبدال روابط ومعرفات القنوات المصدر
  3. إضافة التوقيع
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("fer3oon.modifier")


class ContentModifier:

    def __init__(
        self,
        footer_text: str,
        source_signature_patterns: list,
        replace_links: dict,
        remove_hashtags: list,
        replace_hashtags: dict,
        add_hashtags: list,
        destination_channel: str,
        owner_username: str,
        source_identifiers: list,
        promo_keywords: list,
    ):
        self.footer_text         = footer_text.strip()
        self.replace_links       = replace_links
        self.remove_hashtags     = [h.lower() for h in remove_hashtags]
        self.replace_hashtags    = {k.lower(): v for k, v in replace_hashtags.items()}
        self.add_hashtags        = add_hashtags
        self.destination_channel = destination_channel
        self.owner_username      = owner_username
        self.source_identifiers  = source_identifiers
        self.promo_keywords      = [k.lower() for k in promo_keywords]

        # Footer detection
        self._footer_re = re.compile(
            re.escape(destination_channel), re.IGNORECASE
        )

        # Signature patterns
        self._sig_patterns = [
            re.compile(p, re.IGNORECASE | re.DOTALL)
            for p in source_signature_patterns
        ]

        # Album combined signature pattern
        self._combined_sig_re = re.compile(
            r"⬤\s+[^\n]+\n\s*(?:https?://)?(?:Telegram\.me|t\.me)/(?:ForexBreakingNews|fforexNews)[^\n]*",
            re.IGNORECASE,
        )

    # ─── Public API ───────────────────────────────────────────

    def is_promo(self, text: str) -> bool:
        """True لو الرسالة ترويجية ويجب حذفها."""
        if not text:
            return False
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.promo_keywords)

    async def process(self, text: Optional[str]) -> Optional[str]:
        """
        تطبيق كل قواعد التعديل.
        Returns None لو الرسالة ترويجية.
        """
        if text is None:
            return None

        # 1. فلترة الترويج
        if self.is_promo(text):
            logger.info("رسالة ترويجية — تم حذفها.")
            return None

        # 2. استبدال التوقيع المركب
        text = self._replace_combined_signature(text)

        # 3. استبدال الروابط المباشرة
        text = self._replace_links(text)

        # 4. استبدال أي معرف أو يوزرنيم للقنوات المصدر
        text = self._replace_identifiers(text)

        # 5. الهاشتاجات
        text = self._process_hashtags(text)

        # 6. التوقيع
        text = self._ensure_footer(text)

        # 7. تنظيف المسافات
        text = self._clean(text)

        return text

    # ─── خطوات التعديل ────────────────────────────────────────

    def _replace_combined_signature(self, text: str) -> str:
        """استبدال توقيع ⬤ + رابط المصدر بتوقيعنا."""
        if self._combined_sig_re.search(text):
            text = self._combined_sig_re.sub(self.footer_text, text)
        return text

    def _replace_links(self, text: str) -> str:
        for old, new in self.replace_links.items():
            text = text.replace(old, new)
        return text

    def _replace_identifiers(self, text: str) -> str:
        """
        استبدال أي يوزرنيم أو اسم قناة مصدر في النص.
        @ForexBreakingNews → @X_T_RA_DE_R
        """
        for identifier in self.source_identifiers:
            if identifier.startswith("@"):
                # يوزرنيم → OWNER_USERNAME
                text = text.replace(identifier, self.owner_username)
            elif identifier.startswith("http") or identifier.startswith("t.me") or identifier.startswith("Telegram"):
                # روابط اتعالجت في _replace_links
                pass
            else:
                # اسم القناة بدون @ أو رابط
                text = re.sub(
                    rf"\b{re.escape(identifier)}\b",
                    self.owner_username,
                    text,
                    flags=re.IGNORECASE
                )
        return text

    def _process_hashtags(self, text: str) -> str:
        if not (self.remove_hashtags or self.replace_hashtags or self.add_hashtags):
            return text

        def _transform(match):
            tag = match.group(1).lower()
            if tag in self.remove_hashtags:
                return ""
            if tag in self.replace_hashtags:
                return f"#{self.replace_hashtags[tag]}"
            return match.group(0)

        text = re.sub(r"#([\w\u0600-\u06FF]+)", _transform, text)

        if self.add_hashtags:
            extra = "  ".join(f"#{h}" for h in self.add_hashtags)
            text = f"{text.rstrip()}\n\n{extra}"

        return text

    def _ensure_footer(self, text: str) -> str:
        if not self._footer_re.search(text):
            text = f"{text.rstrip()}\n\n{self.footer_text}"
        return text

    def _clean(self, text: str) -> str:
        lines = text.split("\n")
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines)
