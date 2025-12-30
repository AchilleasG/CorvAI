from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    openai_key: str = os.getenv("OPENAI_KEY")
    google_calendar_credentials_json: Optional[str] = None
    google_calendar_credentials_file: Optional[str] = None
    google_calendar_delegated_user: Optional[str] = None
    google_calendar_default_id: Optional[str] = None
    google_calendar_default_timezone: Optional[str] = "Europe/Athens"

    # Accept extra env vars so a fuller .env file does not raise
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
