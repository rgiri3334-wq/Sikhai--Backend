# ============================================================
#  db/client.py — Supabase Client + DB Initialization
# ============================================================

from supabase import create_client, Client
from loguru import logger
from config import settings


# ── Supabase Client Singleton ─────────────────────────────────
_supabase: Client = None

def get_db() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            settings.supabase_url,
            settings.supabase_service_key   # Use service key server-side
        )
    return _supabase


async def init_db():
    """Called on app startup — verify DB connection and create tables."""
    try:
        db = get_db()
        # Ping by fetching schema info
        db.table("users").select("id").limit(1).execute()
        logger.success("✅ Supabase database connected")
    except Exception as e:
        logger.warning(f"⚠️  DB ping failed (tables may not exist yet): {e}")
        logger.info("Run the SQL in db/schema.sql on your Supabase project")
