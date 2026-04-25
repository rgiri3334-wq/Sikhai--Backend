from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    app_name: str = "Sikai Learning API"
    app_version: str = "1.0.0"
    debug: bool = False
    secret_key: str = "changeme-secret-key-minimum-32-characters-long"
    allowed_origins: str = "http://localhost:3000"

    groq_api_key: str = ""
    groq_model_fast: str = "llama-3.1-8b-instant"
    groq_model_smart: str = "llama-3.3-70b-versatile"

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    jwt_secret: str = "changeme-jwt-secret-minimum-32-characters-long"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080

    max_tokens_course: int = 4000
    max_tokens_tutor: int = 800
    max_tokens_quiz: int = 2000
    tutor_history_limit: int = 10

    rate_limit_per_minute: int = 30
    rate_limit_ai_per_hour: int = 50

    cache_ttl_course: int = 86400
    cache_ttl_quiz: int = 3600
    cache_ttl_user: int = 300

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
