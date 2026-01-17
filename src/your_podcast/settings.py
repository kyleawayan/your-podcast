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

    # User agent for Reddit RSS feeds
    user_agent: str = "your-podcast:v0.1.0 (RSS reader)"

    # Reddit API (optional - for future OAuth support)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_redirect_uri: str = "http://localhost:8080/callback"
    token_encryption_key: str = ""

    # Podcast generation with Podcastfy
    anthropic_api_key: str = ""  # For transcript generation with Claude
    elevenlabs_api_key: str = ""  # For TTS audio generation


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
