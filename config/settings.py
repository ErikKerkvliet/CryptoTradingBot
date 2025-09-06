"""Application settings and configuration loader."""
from __future__ import annotations
import os
from pydantic_settings import BaseSettings
from pydantic import Field, validator

from typing import Optional

class Settings(BaseSettings):
    # Kraken
    KRAKEN_API_KEY: str
    KRAKEN_API_SECRET: str

    # OpenAI
    OPENAI_API_KEY: str

    # Telegram
    TELEGRAM_API_ID: Optional[int]
    TELEGRAM_API_HASH: Optional[str]
    TELEGRAM_BOT_TOKEN: Optional[str]
    TELEGRAM_CHANNEL_ID: str = Field(..., description="Telegram channel id or @handle")

    # Trading
    DRY_RUN: bool = True
    MAX_POSITION_SIZE_PERCENT: float = 5.0
    MIN_CONFIDENCE_THRESHOLD: int = 80
    MAX_DAILY_TRADES: int = 10

    # Misc
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @staticmethod
    @validator("MIN_CONFIDENCE_THRESHOLD")
    def validate_confidence(cls, v):
        if not 0 <= v <= 100:
            raise ValueError("MIN_CONFIDENCE_THRESHOLD must be between 0 and 100")
        return v

settings = Settings()