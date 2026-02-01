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
    gemini_api_key: str = ""  # For transcript generation with Gemini
    elevenlabs_api_key: str = ""  # For TTS audio generation

    # TTS backend: "elevenlabs" or "macos"
    tts_backend: str = "elevenlabs"

    # ElevenLabs voice IDs (find at elevenlabs.io/voice-library)
    elevenlabs_voice_1: str = "okH1aHncYRU2dc9TP3hV"  # Person1 (host asking questions)
    elevenlabs_voice_2: str = "WIX8boagHAO6uMUqxXLz"  # Person2 (host answering)

    # macOS TTS voices (Premium/Siri voices recommended)
    # Install via: System Settings > Accessibility > Spoken Content > System Voice > Manage Voices
    # Or on Sequoia+: VoiceOver Utility > Speech
    macos_voice_1: str = "Zoe (Premium)"  # Person1 (host asking questions)
    macos_voice_2: str = "Lee (Premium)"  # Person2 (host answering)

    # Chatterbox TTS (local neural TTS, requires ~10s reference audio files)
    # Place reference audio in ./data/voices/
    chatterbox_voice_1: str = "./data/voices/person1.wav"  # Person1 reference audio
    chatterbox_voice_2: str = "./data/voices/person2.wav"  # Person2 reference audio


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
