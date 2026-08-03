from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    openai_key: str = os.getenv("OPENAI_KEY")
    xai_key: Optional[str] = os.getenv("XAI_API_KEY")
    xai_base_url: Optional[str] = os.getenv("XAI_BASE_URL") or "https://api.x.ai/v1"
    google_calendar_credentials_json: Optional[str] = None
    google_calendar_credentials_file: Optional[str] = None
    google_calendar_delegated_user: Optional[str] = None
    google_calendar_default_id: Optional[str] = None
    google_calendar_default_timezone: Optional[str] = "Europe/Athens"
    module_secret_key: Optional[str] = os.getenv("MODULE_SECRET_KEY")
    transcription_model: str = os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")

    # Accept extra env vars so a fuller .env file does not raise
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
