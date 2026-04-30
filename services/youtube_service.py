# services/youtube_service.py
# ═══════════════════════════════════════════════════════════════════
# SIKAI YOUTUBE VIDEO FINDER
# Finds best 4-5 minute educational video for each lesson topic
# Uses YouTube Data API v3 — Free quota: 10,000 units/day
# Each search costs 100 units → 100 free searches/day
# ═══════════════════════════════════════════════════════════════════

import httpx
import logging
from typing import Optional
from config import settings

log = logging.getLogger("sikai")

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_URL  = "https://www.googleapis.com/youtube/v3/videos"

# Duration filter: medium = 4-20 min, but we further filter to 4-5 min
# PT4M = 4 minutes, PT5M30S = 5 min 30 sec in ISO 8601 duration format
MIN_DURATION_SECONDS = 180   # 3 minutes minimum
MAX_DURATION_SECONDS = 360   # 6 minutes maximum


async def find_best_video(
    search_query: str,
    topic: str,
    grade: str = "",
    language: str = "mixed",
) -> dict:
    """
    Find the best 4-5 minute educational YouTube video for a lesson.
    Returns dict with: url, title, channel, duration, view_count, thumbnail
    Falls back to YouTube search URL if API fails or no results found.
    """
    if not getattr(settings, "youtube_api_key", ""):
        # No API key — return search URL fallback
        return _make_search_fallback(search_query)

    try:
        # Build search query optimized for Nepal education
        query = _build_query(search_query, topic, grade, language)

        # Step 1: Search for videos
        video_ids = await _search_videos(query)
        if not video_ids:
            return _make_search_fallback(search_query)

        # Step 2: Get video details (duration, views, etc.)
        videos = await _get_video_details(video_ids)
        if not videos:
            return _make_search_fallback(search_query)

        # Step 3: Filter and rank videos
        best = _pick_best_video(videos)
        if not best:
            return _make_search_fallback(search_query)

        return best

    except Exception as e:
        log.warning(f"YouTube API failed for '{search_query}': {e}")
        return _make_search_fallback(search_query)


async def _search_videos(query: str) -> list:
    """Search YouTube and return list of video IDs."""
    params = {
        "part":            "id",
        "q":               query,
        "type":            "video",
        "videoDuration":   "medium",      # 4-20 minutes
        "videoDefinition": "high",        # HD only
        "relevanceLanguage": "en",
        "maxResults":      10,
        "order":           "viewCount",   # Most viewed first
        "safeSearch":      "strict",
        "key":             settings.youtube_api_key,
    }

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(YOUTUBE_SEARCH_URL, params=params)
        r.raise_for_status()
        data = r.json()

    items = data.get("items", [])
    return [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]


async def _get_video_details(video_ids: list) -> list:
    """Get detailed stats for a list of video IDs."""
    params = {
        "part":  "snippet,contentDetails,statistics",
        "id":    ",".join(video_ids),
        "key":   settings.youtube_api_key,
    }

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(YOUTUBE_VIDEO_URL, params=params)
        r.raise_for_status()
        data = r.json()

    return data.get("items", [])


def _pick_best_video(videos: list) -> Optional[dict]:
    """
    Filter videos to 3-6 minutes and pick the one with most views.
    Returns formatted video dict or None if no suitable video found.
    """
    candidates = []

    for v in videos:
        try:
            # Parse duration
            duration_str = v.get("contentDetails", {}).get("duration", "")
            duration_sec = _parse_duration(duration_str)

            # Filter: must be between 3-6 minutes
            if not (MIN_DURATION_SECONDS <= duration_sec <= MAX_DURATION_SECONDS):
                continue

            # Get stats
            stats     = v.get("statistics", {})
            view_count = int(stats.get("viewCount", 0))
            like_count = int(stats.get("likeCount", 0))

            # Must have at least 10,000 views to be trustworthy
            if view_count < 10_000:
                continue

            snippet   = v.get("snippet", {})
            video_id  = v["id"]

            candidates.append({
                "url":         f"https://www.youtube.com/watch?v={video_id}",
                "embed_url":   f"https://www.youtube.com/embed/{video_id}",
                "title":       snippet.get("title", ""),
                "channel":     snippet.get("channelTitle", ""),
                "thumbnail":   snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "duration_sec": duration_sec,
                "duration_str": _format_duration(duration_sec),
                "view_count":  view_count,
                "view_count_str": _format_views(view_count),
                "like_count":  like_count,
                "found":       True,
            })

        except Exception as e:
            log.debug(f"Skipping video: {e}")
            continue

    if not candidates:
        return None

    # Sort by view count descending — most popular first
    candidates.sort(key=lambda x: x["view_count"], reverse=True)
    return candidates[0]


def _build_query(search_query: str, topic: str, grade: str, language: str) -> str:
    """Build optimized YouTube search query for Nepal education."""
    base = search_query or topic

    # Add grade context
    grade_map = {
        "grade6-8":   "class 8",
        "grade9-10":  "class 10 SEE",
        "grade11-12": "class 12 NEB",
        "loksewa":    "lok sewa",
        "career":     "tutorial",
    }
    grade_suffix = grade_map.get(grade, "tutorial")

    # Language preference
    if language == "nepali":
        lang_suffix = "Nepali"
    else:
        lang_suffix = ""

    parts = [base, grade_suffix]
    if lang_suffix:
        parts.append(lang_suffix)
    parts.append("explained")

    return " ".join(p for p in parts if p)


def _parse_duration(duration: str) -> int:
    """Convert ISO 8601 duration (PT4M30S) to seconds."""
    import re
    if not duration:
        return 0
    hours   = int(re.search(r"(\d+)H", duration).group(1)) if re.search(r"(\d+)H", duration) else 0
    minutes = int(re.search(r"(\d+)M", duration).group(1)) if re.search(r"(\d+)M", duration) else 0
    seconds = int(re.search(r"(\d+)S", duration).group(1)) if re.search(r"(\d+)S", duration) else 0
    return hours * 3600 + minutes * 60 + seconds


def _format_duration(seconds: int) -> str:
    """Format seconds to MM:SS string."""
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _format_views(count: int) -> str:
    """Format view count to readable string."""
    if count >= 1_000_000:
        return f"{count/1_000_000:.1f}M views"
    if count >= 1_000:
        return f"{count/1_000:.0f}K views"
    return f"{count} views"


def _make_search_fallback(query: str) -> dict:
    """Return YouTube search URL when API is unavailable."""
    encoded = query.replace(" ", "+")
    return {
        "url":          f"https://www.youtube.com/results?search_query={encoded}&sp=EgQIBBAB",
        "embed_url":    None,
        "title":        f"Search: {query}",
        "channel":      "YouTube Search",
        "thumbnail":    None,
        "duration_str": "4-6 min",
        "view_count_str": "",
        "found":        False,
    }
