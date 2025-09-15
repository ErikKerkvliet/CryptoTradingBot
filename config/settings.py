"""Loads and validates application settings from a .env file."""
from __future__ import annotations
from typing import Optional, List, Union
from pydantic_settings import BaseSettings
from pathlib import Path

# --- MODIFICATION START ---
# Define the project's base directory (the 'CryptoTradingBot-master' folder)
# This ensures that database files and other resources are always located correctly.
BASE_DIR = Path(__file__).resolve().parent.parent
# --- MODIFICATION END ---

class Settings(BaseSettings):
    """Defines the application's configuration settings using Pydantic."""

    # -- General Application Settings --
    EXCHANGE: str = "KRAKEN"         # The exchange to trade on: "KRAKEN" or "MEXC"
    TRADING_MODE: str = "SPOT"       # The trading mode: "SPOT" or "FUTURES"
    LOG_LEVEL: str = "INFO"          # Logging level, e.g., "DEBUG", "INFO", "WARNING"

    # -- API Keys --
    KRAKEN_API_KEY: Optional[str] = None
    KRAKEN_API_SECRET: Optional[str] = None
    MEXC_API_KEY: Optional[str] = None
    MEXC_API_SECRET: Optional[str] = None
    OPENAI_API_KEY: str

    # -- Telegram API Settings --
    TELEGRAM_API_ID: int
    TELEGRAM_API_HASH: str
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # -- Telegram Channel IDs --
    TELEGRAM_CHANNEL_ID: Optional[str] = None        # Channel for live trades
    TELEGRAM_DRY_RUN_CHANNEL_ID: Optional[str] = None # Channel for simulated trades

    # -- Core Trading Configuration --
    DRY_RUN: bool = True
    MAX_POSITION_SIZE_PERCENT: float = 5.0  # Max % of quote currency balance to use for a trade
    ORDER_SIZE_USD: float = 0.0             # Fixed order size in USD (overrides percentage if > 0)
    MIN_CONFIDENCE_THRESHOLD: int = 80      # Minimum signal confidence to execute a trade (1-100)
    MAX_DAILY_TRADES: int = 10              # Maximum number of BUY trades to execute in a 24-hour period (SELL trades don't count)

    # -- Futures-Specific Settings --
    DEFAULT_LEVERAGE: int = 10              # Default leverage if not specified in the signal

    class Config:
        """Pydantic model configuration."""
        env_file = ".env"  # Load settings from a .env file
        extra = "ignore"   # Ignore extra fields in the .env file

    @property
    def target_channels(self) -> List[Union[int, str]]:
        """
        Returns a list of channel IDs to monitor based on the DRY_RUN setting.
        This allows the bot to listen to different channels for live vs. simulated trading.
        Handles comma-separated channel IDs in the environment variables.
        """
        channels = []
        raw_channel_string = self.TELEGRAM_DRY_RUN_CHANNEL_ID if self.DRY_RUN else self.TELEGRAM_CHANNEL_ID

        if raw_channel_string:
            # Split the string by commas to get a list of channels
            raw_channels = [channel.strip() for channel in raw_channel_string.split(',')]

            for channel in raw_channels:
                if channel:
                    try:
                        # Convert to int if it's a numeric ID (e.g., -100123456)
                        channels.append(int(channel))
                    except (ValueError, TypeError):
                        # Otherwise, keep as a string for public channel usernames (e.g., '@channel_name')
                        channels.append(channel)
        return channels

    def validate_required_fields(self):
        """
        Validates that all necessary environment variables are set based on the
        selected trading mode, exchange, and dry_run status. This prevents
        runtime errors due to missing configuration.
        """
        # --- Channel ID Validation ---
        if self.DRY_RUN:
            if not self.TELEGRAM_DRY_RUN_CHANNEL_ID:
                raise ValueError(
                    "Missing required environment variable: TELEGRAM_DRY_RUN_CHANNEL_ID (required when DRY_RUN=true)"
                )
        else: # Live Trading
            if not self.TELEGRAM_CHANNEL_ID:
                raise ValueError(
                    "Missing required environment variable: TELEGRAM_CHANNEL_ID (required when DRY_RUN=false)"
                )

            # --- Live Trading API Key Validation ---
            mode = self.TRADING_MODE.upper()
            exchange = self.EXCHANGE.upper()

            if mode == "SPOT":
                if exchange == "KRAKEN":
                    if not self.KRAKEN_API_KEY or not self.KRAKEN_API_SECRET:
                        raise ValueError("KRAKEN_API_KEY and KRAKEN_API_SECRET are required for live SPOT trading on Kraken.")
                elif exchange == "MEXC":
                    if not self.MEXC_API_KEY or not self.MEXC_API_SECRET:
                        raise ValueError("MEXC_API_KEY and MEXC_API_SECRET are required for live SPOT trading on MEXC.")
                else:
                    raise ValueError(f"Unsupported EXCHANGE for SPOT trading: '{self.EXCHANGE}'. Must be 'KRAKEN' or 'MEXC'.")

            elif mode == "FUTURES":
                if exchange != "MEXC":
                    raise ValueError(f"Unsupported EXCHANGE for FUTURES trading: '{self.EXCHANGE}'. Currently, only 'MEXC' is supported.")
                if not self.MEXC_API_KEY or not self.MEXC_API_SECRET:
                    raise ValueError("MEXC_API_KEY and MEXC_API_SECRET are required for live FUTURES trading.")

            else:
                raise ValueError(f"Unsupported TRADING_MODE: '{self.TRADING_MODE}'. Must be 'SPOT' or 'FUTURES'.")

# Create a single, global instance of the settings to be used throughout the application
settings = Settings()