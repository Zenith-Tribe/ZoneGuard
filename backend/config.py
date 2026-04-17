from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_env: str = "development"
    debug: bool = True
    database_url: str = "postgresql+asyncpg://zoneguard:zoneguard_dev@localhost:5432/zoneguard"
    redis_url: str = "redis://localhost:6379/0"
    openweathermap_api_key: str = ""
    gemini_api_key: str = ""
    jwt_secret: str = "zoneguard-demo-secret-2026"
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000,https://zenith-tribe.github.io,https://*.railway.app"
    allowed_hosts: str = "*"  # Railway proxy requires permissive host header

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
