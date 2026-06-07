"""
modules/content_modifier.py
────────────────────────────
Applies all transformation rules to message text before forwarding:
  - Replace / remove source channel signatures
  - Replace direct links
  - Modify hashtags (remove / replace / add)
  - Append footer if missing
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("fer3oon.modifier")


class ContentModifier:
    """
    Stateless transformer.  Receives raw text, returns modified text.
    All rules are injected at construction time from config/settings.py.
    """

    def __init__(
        self,
        footer_text: str,
        source_signature_patterns: list[str],
        replace_links: dict[str, str],
        remove_hashtags: list[str],
        replace_hashtags: dict[str, str],
        add_hashtags: list[str],
        destination_channel: str,
    ):
        self.footer_text = footer_text.strip()
        self.replace_links = replace_links
        self.remove_hashtags = [h.lower() for h in remove_hashtags]
        self.replace_hashtags = {k.lower(): v for k, v in replace_hashtags.items()}
        self.add_hashtags = add_hashtags
        self.destination_channel = destination_channel

        # Pre-compile signature patterns for performance
        self._sig_patterns = [
            re.compile(p, re.IGNORECASE | re.DOTALL)
            for p in source_signature_patterns
        ]

        # Footer detection: true if text ends with destination channel link
        self._footer_detect_re = re.compile(
            re.escape(destination_channel), re.IGNORECASE
        )

    # ─── Public API ───────────────────────────────────────────

    def process(self, text: Optional[str]) -> Optional[str]:
        """
        Apply all modification rules to *text* and return the cleaned version.
        Returns None if input is None.
        """
        if text is None:
            return None

        text = self._replace_source_signatures(text)
        text = self._replace_direct_links(text)
        text = self._process_hashtags(text)
        text = self._ensure_footer(text)
        text = self._clean_trailing_whitespace(text)

        return text

    # ─── Rule implementations ─────────────────────────────────

    def _replace_source_signatures(self, text: str) -> str:
        """
        Find full source-channel signature blocks and replace with footer.
        Strategy: detect the ⬤ block containing source channel ref and swap it.
        """
        # Pattern: the ⬤ line followed by a t.me/source link on the next line
        # This handles the exact examples in the spec.
        combined_pattern = re.compile(
            r"⬤\s+[^\n]+\n\s*(?:https?://)?(?:Telegram\.me|t\.me)/ForexBreakingNews[^\n]*",
            re.IGNORECASE,
        )
        if combined_pattern.search(text):
            text = combined_pattern.sub(self.footer_text, text)
            return text

        # Fallback: apply individual signature patterns
        for pattern in self._sig_patterns:
            if pattern.search(text):
                # Replace only if it looks like a standalone signature block
                text = pattern.sub("", text)
                logger.debug("Removed source signature via pattern")

        return text

    def _replace_direct_links(self, text: str) -> str:
        """Replace all known source channel links with destination links."""
        for old, new in self.replace_links.items():
            text = text.replace(old, new)
        return text

    def _process_hashtags(self, text: str) -> str:
        """Remove, replace, and add hashtags according to config."""
        if not (self.remove_hashtags or self.replace_hashtags or self.add_hashtags):
            return text

        def _transform_tag(match: re.Match) -> str:
            tag_body = match.group(1)          # text after #
            tag_lower = tag_body.lower()

            if tag_lower in self.remove_hashtags:
                return ""                       # delete entirely

            if tag_lower in self.replace_hashtags:
                return f"#{self.replace_hashtags[tag_lower]}"

            return match.group(0)               # keep as-is

        # Match hashtags (Arabic + Latin characters)
        text = re.sub(r"#([\w\u0600-\u06FF]+)", _transform_tag, text)

        # Add new hashtags at end
        if self.add_hashtags:
            extra = "  ".join(f"#{h}" for h in self.add_hashtags)
            text = f"{text.rstrip()}\n\n{extra}"

        return text

    def _ensure_footer(self, text: str) -> str:
        """Append footer if the destination channel is not already mentioned."""
        if not self._footer_detect_re.search(text):
            text = f"{text.rstrip()}\n\n{self.footer_text}"
            logger.debug("Footer appended to post")
        return text

    def _clean_trailing_whitespace(self, text: str) -> str:
        """Remove trailing blank lines while preserving internal formatting."""
        lines = text.split("\n")
        # Strip trailing empty lines
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines)

    # ─── Debug helper ─────────────────────────────────────────

    def preview(self, original: str) -> tuple[str, str]:
        """Return (original, modified) for side-by-side comparison."""
        return original, self.process(original)
