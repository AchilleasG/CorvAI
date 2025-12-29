from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    openai_key: str = os.getenv("OPENAI_KEY")

    # Accept extra env vars so a fuller .env file does not raise
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
