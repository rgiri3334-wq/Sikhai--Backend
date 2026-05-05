from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────
    app_name:    str  = "Sikai Learning API"
    app_version: str  = "6.0.0"
    debug:       bool = False
    secret_key:  str  = "changeme-secret-key-minimum-32-characters-long"
    allowed_origins: str = "http://localhost:3000"

    # ── AI Provider ──────────────────────────────────────────────
    # Set in Railway Variables to switch:
    # "groq"   → Llama 3 via Groq (default, free tier)
    # "openai" → GPT-4o Mini via OpenAI (better Nepali quality)
    ai_provider: str = "groq"

    # ── Groq (Llama 3) ───────────────────────────────────────────
    groq_api_key:     str = ""
    groq_model_fast:  str = "llama-3.1-8b-instant"
    groq_model_smart: str = "llama-3.3-70b-versatile"

    # ── OpenAI (GPT-4o Mini) ─────────────────────────────────────
    openai_api_key:    str = ""
    openai_model_fast: str = "gpt-4o-mini"
    openai_model_smart:str = "gpt-4o-mini"

    # ── YouTube Data API ─────────────────────────────────────────
    # Get free key from console.cloud.google.com
    # Enable "YouTube Data API v3" → Create API Key
    youtube_api_key: str = ""

    # ── Supabase ─────────────────────────────────────────────────
    supabase_url:         str = ""
    supabase_anon_key:    str = ""
    supabase_service_key: str = ""

    # ── Redis (Upstash) ──────────────────────────────────────────
    upstash_redis_rest_url:   str = ""
    upstash_redis_rest_token: str = ""

    # ── Auth ─────────────────────────────────────────────────────
    jwt_secret:         str = "changeme-jwt-secret-minimum-32-characters-long"
    jwt_algorithm:      str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 days

    # ── AI Token Limits ──────────────────────────────────────────
    max_tokens_course: int = 4000
    max_tokens_tutor:  int = 800
    max_tokens_quiz:   int = 2000
    tutor_history_limit: int = 10

    # ── Rate Limiting ────────────────────────────────────────────
    rate_limit_per_minute:  int = 30
    rate_limit_ai_per_hour: int = 50

    # ── Cache TTL ────────────────────────────────────────────────
    cache_ttl_course: int = 86400  # 24 hours
    cache_ttl_quiz:   int = 3600   # 1 hour
    cache_ttl_user:   int = 300    # 5 minutes

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
