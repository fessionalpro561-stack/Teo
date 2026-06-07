"""
modules/logger.py
─────────────────
Centralized logging setup for FER3OON Sync.
Outputs to both console (colored) and rotating file.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


class ColorFormatter(logging.Formatter):
    """Adds ANSI color codes to console log output."""

    COLORS = {
        "DEBUG":    "\033[36m",    # Cyan
        "INFO":     "\033[32m",    # Green
        "WARNING":  "\033[33m",    # Yellow
        "ERROR":    "\033[31m",    # Red
        "CRITICAL": "\033[35m",    # Magenta
    }
    RESET = "\033[0m"
    BOLD  = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{self.BOLD}{record.levelname:<8}{self.RESET}"
        return super().format(record)


def setup_logger(
    log_level: str = "INFO",
    log_file: str = "logs/sync.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    """
    Create and configure the root logger.
    Returns the 'fer3oon' logger that all modules should use.
    """
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Root logger for this project
    root = logging.getLogger("fer3oon")
    root.setLevel(numeric_level)

    # Avoid adding duplicate handlers on re-init
    if root.handlers:
        return root

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # ── Console handler (colored) ──────────────────────────────
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(ColorFormatter(fmt, datefmt=date_fmt))
    root.addHandler(console_handler)

    # ── Rotating file handler ─────────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
    root.addHandler(file_handler)

    return root


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the 'fer3oon' namespace."""
    return logging.getLogger(f"fer3oon.{name}")
