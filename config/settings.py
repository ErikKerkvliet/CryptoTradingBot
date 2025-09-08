"""Loads and validates application settings from a .env file."""
from __future__ import annotations
from typing import Optional, List, Union
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Defines the application's configuration settings."""

    # Kraken API
    KRAKEN_API_KEY: str
    KRAKEN_API_SECRET: str

    # OpenAI API
    OPENAI_API_KEY: str

    # Telegram API
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # Channel IDs
    TELEGRAM_CHANNEL_ID: Optional[str] = None
    TELEGRAM_DRY_RUN_CHANNEL_ID: Optional[str] = None

    # Trading Configuration
    DRY_RUN: bool = True
    MAX_POSITION_SIZE_PERCENT: float = 5.0
    ORDER_SIZE_USD: float = 0.0
    MIN_CONFIDENCE_THRESHOLD: int = 80
    MAX_DAILY_TRADES: int = 10

    # Misc
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def target_channels(self) -> List[Union[int, str]]:
        """
        Returns a list of channel IDs to monitor based on the DRY_RUN setting.
        """
        channels = []
        raw_channels = []
        if self.DRY_RUN:
            raw_channels = [self.TELEGRAM_DRY_RUN_CHANNEL_ID]
        else:
            raw_channels = [self.TELEGRAM_CHANNEL_ID]

        for channel in raw_channels:
            if channel:
                try:
                    # Convert to int if it's a numeric ID (e.g., -100123456)
                    channels.append(int(channel))
                except (ValueError, TypeError):
                    # Otherwise, keep as a string (e.g., a public channel username)
                    channels.append(channel)
        return channels

    def validate_required_fields(self):
        """
        Validates that the necessary environment variables are set based on the mode.
        """
        if self.DRY_RUN:
            if not self.TELEGRAM_DRY_RUN_CHANNEL_ID:
                raise ValueError(
                    "Missing required environment variable: TELEGRAM_DRY_RUN_CHANNEL_ID (required when DRY_RUN=true)"
                )
        else:
            if not self.TELEGRAM_CHANNEL_ID:
                raise ValueError(
                    "Missing required environment variable: TELEGRAM_CHANNEL_ID (required when DRY_RUN=false)"
                )

settings = Settings()