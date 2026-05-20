from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://zheu:zheu@localhost:5432/zheu"
    jwt_secret: str = "dev-secret-key"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    auth_service_url: str = "http://localhost:8001"
    session_service_url: str = "http://localhost:8002"
    tickets_service_url: str = "http://localhost:8003"
    news_service_url: str = "http://localhost:8004"
    notifications_service_url: str = "http://localhost:8005"


@lru_cache
def get_settings() -> Settings:
    return Settings()
