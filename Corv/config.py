from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    openai_key: str = os.getenv("OPENAI_KEY")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()