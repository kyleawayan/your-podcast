"""Application settings using Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/your_podcast"

    # User agent for Reddit JSON API
    user_agent: str = "your-podcast:v0.1.0 (JSON reader)"

    # Podcast generation with Podcastfy
    anthropic_api_key: str = ""  # For transcript generation with Claude
    elevenlabs_api_key: str = ""  # For TTS audio generation


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
