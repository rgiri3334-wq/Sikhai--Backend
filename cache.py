# ============================================================
#  services/cache.py — Redis Cache via Upstash (Free Tier)
#  Falls back to in-memory dict if Redis not configured
# ============================================================

import json
from loguru import logger
from typing import Optional, Any
from config import settings


# In-memory fallback cache (dev / no Redis)
_memory_cache: dict = {}


async def init_cache():
    """Initialize cache on startup."""
    if settings.upstash_redis_rest_url:
        try:
            # Test connection
            await cache_set("__ping__", "pong", ttl=10)
            result = await cache_get("__ping__")
            if result == "pong":
                logger.success("✅ Upstash Redis connected")
            else:
                logger.warning("⚠️  Redis ping failed, using in-memory cache")
        except Exception as e:
            logger.warning(f"⚠️  Redis unavailable ({e}), using in-memory cache")
    else:
        logger.info("📦 No Redis URL configured — using in-memory cache (dev mode)")


async def cache_get(key: str) -> Optional[Any]:
    """Get value from cache. Returns None if not found or expired."""
    if settings.upstash_redis_rest_url:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.upstash_redis_rest_url}/get/{key}",
                    headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
                    timeout=3.0,
                )
                data = response.json()
                if data.get("result"):
                    return json.loads(data["result"])
                return None
        except Exception as e:
            logger.debug(f"Cache get error (non-critical): {e}")
            return _memory_cache.get(key)
    else:
        return _memory_cache.get(key)


async def cache_set(key: str, value: Any, ttl: int = 3600) -> bool:
    """Set value in cache with TTL in seconds."""
    serialized = json.dumps(value, default=str)

    if settings.upstash_redis_rest_url:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{settings.upstash_redis_rest_url}/set/{key}",
                    headers={
                        "Authorization": f"Bearer {settings.upstash_redis_rest_token}",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps([serialized, "EX", ttl]),
                    timeout=3.0,
                )
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"Cache set error (non-critical): {e}")
            _memory_cache[key] = value
            return False
    else:
        _memory_cache[key] = value
        return True


async def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    _memory_cache.pop(key, None)

    if settings.upstash_redis_rest_url:
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.get(
                    f"{settings.upstash_redis_rest_url}/del/{key}",
                    headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
                    timeout=3.0,
                )
        except Exception as e:
            logger.debug(f"Cache delete error (non-critical): {e}")
    return True


async def cache_invalidate_user(user_id: str):
    """Invalidate all cached data for a user (on profile update)."""
    keys_to_delete = [k for k in _memory_cache if user_id in k]
    for key in keys_to_delete:
        await cache_delete(key)
