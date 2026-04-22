# ============================================================
#  utils/helpers.py — Shared Utility Functions
# ============================================================

import re
import uuid
from datetime import datetime


def slugify(text: str) -> str:
    """Convert 'Photosynthesis Nepal' → 'photosynthesis-nepal'"""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def generate_id() -> str:
    return str(uuid.uuid4())


def utcnow_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def truncate(text: str, max_len: int = 100) -> str:
    return text[:max_len] + "..." if len(text) > max_len else text


def estimate_read_time(text: str, wpm: int = 150) -> int:
    """Estimate read time in minutes (Nepali readers ~150wpm)."""
    word_count = len(text.split())
    return max(1, round(word_count / wpm))


def sanitize_topic(topic: str) -> str:
    """Clean user input topic string."""
    topic = topic.strip()
    topic = re.sub(r'\s+', ' ', topic)
    topic = re.sub(r'[<>"\']', '', topic)
    return topic[:200]


def xp_to_level(xp: int) -> str:
    """Convert XP to display level."""
    if xp >= 5000: return "🏆 Master"
    if xp >= 2000: return "⭐ Expert"
    if xp >= 800:  return "🔥 Advanced"
    if xp >= 300:  return "⚡ Intermediate"
    return "🌱 Beginner"
