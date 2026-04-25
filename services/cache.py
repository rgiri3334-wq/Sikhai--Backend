import json
import logging
from typing import Optional, Any
from config import settings

log = logging.getLogger("sikai")
_mem: dict = {}


async def init_cache():
    if settings.upstash_redis_rest_url:
        try:
            await cache_set("__ping__", "pong", ttl=10)
            r = await cache_get("__ping__")
            log.info("✅ Redis connected" if r == "pong" else "⚠️  Redis ping failed, using memory cache")
        except Exception as e:
            log.warning(f"Redis unavailable: {e}, using memory cache")
    else:
        log.info("Using in-memory cache (no Redis URL set)")


async def cache_get(key: str) -> Optional[Any]:
    if settings.upstash_redis_rest_url:
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                r = await c.get(
                    f"{settings.upstash_redis_rest_url}/get/{key}",
                    headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}"},
                    timeout=3.0,
                )
                d = r.json()
                return json.loads(d["result"]) if d.get("result") else None
        except Exception:
            return _mem.get(key)
    return _mem.get(key)


async def cache_set(key: str, value: Any, ttl: int = 3600) -> bool:
    serialized = json.dumps(value, default=str)
    if settings.upstash_redis_rest_url:
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                r = await c.post(
                    f"{settings.upstash_redis_rest_url}/set/{key}",
                    headers={"Authorization": f"Bearer {settings.upstash_redis_rest_token}", "Content-Type": "application/json"},
                    content=json.dumps([serialized, "EX", ttl]),
                    timeout=3.0,
                )
                return r.status_code == 200
        except Exception:
            _mem[key] = value
            return False
    _mem[key] = value
    return True


async def cache_delete(key: str) -> bool:
    _mem.pop(key, None)
    return True
