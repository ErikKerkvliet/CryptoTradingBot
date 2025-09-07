"""Application settings and configuration loader."""
from __future__ import annotations
import os
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Kraken
    KRAKEN_API_KEY: str = Field(default="", description="Kraken API key")
    KRAKEN_API_SECRET: str = Field(default="", description="Kraken API secret")

    # OpenAI
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key")

    # Telegram
    TELEGRAM_API_ID: Optional[int] = Field(default=None, description="Telegram API ID")
    TELEGRAM_API_HASH: Optional[str] = Field(default=None, description="Telegram API hash")
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, description="Telegram bot token")
    TELEGRAM_CHANNEL_ID: str = Field(default="", description="Telegram channel id or @handle for live trades")
    TELEGRAM_DRY_RUN_CHANNEL_ID: str = Field(default="", description="Telegram channel id for dry-run trades")

    # Trading
    DRY_RUN: bool = os.getenv('DRY_RUN') == 'true'
    MAX_POSITION_SIZE_PERCENT: float = 5.0
    ORDER_SIZE_USD: float = Field(
        default=0.0,
        description="Fixed order size in quote currency (e.g., USDC). If > 0, this overrides MAX_POSITION_SIZE_PERCENT."
    )
    MIN_CONFIDENCE_THRESHOLD: int = 80
    MAX_DAILY_TRADES: int = 10

    # Misc
    LOG_LEVEL: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"
    }

    def model_post_init(self, __context: any) -> None:
        """
        Deze methode wordt aangeroepen nadat Pydantic de instellingen heeft geladen.
        We gebruiken het om de TELEGRAM_CHANNEL_ID conditioneel in te stellen.
        """
        if self.DRY_RUN and self.TELEGRAM_DRY_RUN_CHANNEL_ID:
            print("DRY_RUN is ingeschakeld. Schakelen naar test Telegram-kanaal.")
            self.TELEGRAM_CHANNEL_ID = self.TELEGRAM_DRY_RUN_CHANNEL_ID
        return super().model_post_init(__context)

    @field_validator("MIN_CONFIDENCE_THRESHOLD")
    @classmethod
    def validate_confidence(cls, v):
        if not 0 <= v <= 100:
            raise ValueError("MIN_CONFIDENCE_THRESHOLD must be between 0 and 100")
        return v

    def validate_required_fields(self):
        """Validate that required fields are present for the bot to work"""
        missing_fields = []

        if not self.KRAKEN_API_KEY:
            missing_fields.append("KRAKEN_API_KEY")
        if not self.KRAKEN_API_SECRET:
            missing_fields.append("KRAKEN_API_SECRET")
        if not self.OPENAI_API_KEY:
            missing_fields.append("OPENAI_API_KEY")
        if not self.TELEGRAM_API_ID:
            missing_fields.append("TELEGRAM_API_ID")
        if not self.TELEGRAM_API_HASH:
            missing_fields.append("TELEGRAM_API_HASH")
        if not self.TELEGRAM_CHANNEL_ID:
            missing_fields.append("TELEGRAM_CHANNEL_ID")

        if missing_fields:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_fields)}")

# Create settings instance
try:
    settings = Settings()
except Exception as e:
    print(f"Error loading settings: {e}")
    print("Please make sure your .env file exists and contains all required variables.")
    print("Check .env.example for the required format.")
    raise