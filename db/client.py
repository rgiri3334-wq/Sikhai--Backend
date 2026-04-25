import logging
from supabase import create_client, Client
from config import settings

log = logging.getLogger("sikai")
_supabase: Client = None


def get_db() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(settings.supabase_url, settings.supabase_service_key)
    return _supabase


async def init_db():
    try:
        db = get_db()
        db.table("users").select("id").limit(1).execute()
        log.info("✅ Supabase connected")
    except Exception as e:
        log.warning(f"⚠️  DB ping failed: {e}")
        log.info("Make sure you ran db/schema.sql in Supabase SQL editor")
