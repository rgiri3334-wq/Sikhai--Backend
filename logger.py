# ============================================================
#  utils/logger.py — Structured Logging with Loguru
# ============================================================

import sys
from loguru import logger
from config import settings


def setup_logging():
    logger.remove()  # Remove default handler

    # Console output
    logger.add(
        sys.stdout,
        level="DEBUG" if settings.debug else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File output — rotating daily, keep 7 days
    logger.add(
        "logs/sikai_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        level="INFO",
        format="{time} | {level} | {name}:{line} — {message}",
        compression="zip",
    )

    logger.info("📝 Logging initialized")
