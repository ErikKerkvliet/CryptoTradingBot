"""Enhanced settings.py with channel configuration support - ONLY loads from .env"""
from __future__ import annotations
from typing import Optional, List, Union, Dict
from pydantic_settings import BaseSettings
from pathlib import Path
import os

# Define the project's base directory
BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """Defines the application's configuration settings using Pydantic."""

    # -- General Application Settings --
    EXCHANGE: str = "KRAKEN"
    TRADING_MODE: str = "SPOT"
    LOG_LEVEL: str = "INFO"

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
    TELEGRAM_CHANNEL_ID: Optional[str] = None
    TELEGRAM_DRY_RUN_CHANNEL_ID: Optional[str] = None

    # -- Core Trading Configuration --
    DRY_RUN: bool = True
    MAX_POSITION_SIZE_PERCENT: float = 5.0
    ORDER_SIZE_USD: float = 0.0
    MIN_CONFIDENCE_THRESHOLD: int = 80
    MAX_DAILY_TRADES: int = 10
    DEFAULT_STOP_LOSS_PERCENTAGE: float = 2.0

    # -- Futures-Specific Settings --
    DEFAULT_LEVERAGE: int = 10

    # -- Auto Sell Monitor Configuration --
    AUTO_SELL_MONITOR: bool = False

    # -- Channel-Specific Configurations --
    # Format: "channel1:USDT:1000&BTC:0.1,channel2:USDT:2000"
    CHANNEL_WALLET_CONFIGS: Optional[str] = None

    # -- Trade Execution Control --
    ENABLE_TRADES: bool = False

    class Config:
        # CRITICAL: Only load from .env file, never from .env.example
        env_file = str(BASE_DIR / ".env")  # Explicit path to .env only
        env_file_encoding = "utf-8"
        extra = "ignore"
        case_sensitive = True

        # Ensure we don't accidentally load from other files
        env_ignore_empty = True

    def __init__(self, **kwargs):
        """Initialize settings with explicit .env file validation."""
        # Check that .env exists before trying to load
        env_file_path = BASE_DIR / ".env"

        if not env_file_path.exists():
            raise FileNotFoundError(
                f"❌ Required .env file not found at: {env_file_path}\n"
                f"   Please copy .env.example to .env:\n"
                f"   cp .env.example .env\n"
                f"   Then edit .env with your actual credentials."
            )

        # Debug: Print what file we're actually loading from
        print(f"🔧 Loading settings from: {env_file_path}")
        print(f"🔧 File exists: {env_file_path.exists()}")
        print(f"🔧 File size: {env_file_path.stat().st_size if env_file_path.exists() else 'N/A'} bytes")

        super().__init__(**kwargs)

        # Additional validation after loading
        self._validate_not_template_values()

    def _validate_not_template_values(self):
        """Ensure we didn't accidentally load template values."""
        template_indicators = [
            "your_", "_here", "api_key_here", "api_secret_here",
            "openai_api_key", "telegram_api_id", "kraken_api_key",
            "mexc_api_key", "telegram_api_hash"
        ]

        # Check critical fields for template values
        fields_to_check = {
            'OPENAI_API_KEY': self.OPENAI_API_KEY,
            'TELEGRAM_API_HASH': self.TELEGRAM_API_HASH,
        }

        for field_name, field_value in fields_to_check.items():
            if field_value and any(indicator in str(field_value).lower() for indicator in template_indicators):
                raise ValueError(
                    f"❌ {field_name} contains template placeholder values!\n"
                    f"   Value: {field_value}\n"
                    f"   Please edit your .env file with real credentials.\n"
                    f"   The .env file should contain actual values, not the template placeholders."
                )

    @property
    def target_channels(self) -> List[Union[int, str]]:
        """Returns a list of channel IDs to monitor based on the DRY_RUN setting."""
        channels = []
        raw_channel_string = self.TELEGRAM_DRY_RUN_CHANNEL_ID if self.DRY_RUN else self.TELEGRAM_CHANNEL_ID

        if raw_channel_string:
            raw_channels = [channel.strip() for channel in raw_channel_string.split(',')]

            for channel in raw_channels:
                if channel:
                    try:
                        channels.append(int(channel))
                    except (ValueError, TypeError):
                        channels.append(channel)
        return channels

    @property
    def channel_wallet_configurations(self) -> Dict[str, Dict[str, float]]:
        """
        Parse channel wallet configurations from the environment variable.
        This ensures all target channels have a default configuration, which is
        then overridden by specific settings in CHANNEL_WALLET_CONFIGS.

        Format: "channel1:USDT:1000&BTC:0.1,channel2:USDT:2000"
        - Channels are separated by commas (,).
        - Currencies within a channel are separated by ampersands (&).
        """
        # 1. Start with default wallets for ALL target channels.
        configs: Dict[str, Dict[str, float]] = {}
        default_amount = 1000.0
        default_currency = "USDT"

        print(f"🔧 Initializing default wallets for all target channels: {self.target_channels}")
        for channel in self.target_channels:
            channel_name = str(channel).replace('@', '')
            if channel_name:  # Ensure we don't add empty strings
                configs[channel_name] = {default_currency: default_amount}

        # 2. If CHANNEL_WALLET_CONFIGS is set, use it to override the defaults.
        print(f"🔧 Parsing CHANNEL_WALLET_CONFIGS raw value: '{self.CHANNEL_WALLET_CONFIGS}'")
        if self.CHANNEL_WALLET_CONFIGS and self.CHANNEL_WALLET_CONFIGS.strip():
            try:
                channel_configs_str = self.CHANNEL_WALLET_CONFIGS.split(',')
                for config_str in channel_configs_str:
                    config_str = config_str.strip()
                    if ':' in config_str:
                        parts = config_str.split(':', 1)
                        if len(parts) == 2:
                            channel_name = parts[0].strip().replace('@', '')
                            currencies_str = parts[1].strip()

                            if channel_name:
                                # This will override the default wallet for this channel
                                configs[channel_name] = {}

                                currency_pairs = currencies_str.split('&')
                                for pair_str in currency_pairs:
                                    pair_parts = pair_str.split(':')
                                    if len(pair_parts) == 2:
                                        currency = pair_parts[0].strip().upper()
                                        amount = float(pair_parts[1].strip())

                                        print(f"   -> Found override for '{channel_name}': {amount} {currency}")
                                        configs[channel_name][currency] = amount
                                    else:
                                        print(f"   -> Warning: Skipping malformed currency pair: {pair_str}")
                            else:
                                print(f"   -> Warning: Skipping invalid config entry (no channel name): {config_str}")
                        else:
                            print(f"   -> Warning: Skipping malformed config entry (expected channel:details): {config_str}")
            except Exception as e:
                print(f"⚠️ Warning: Error parsing CHANNEL_WALLET_CONFIGS: {e}")
                print("   Continuing with default configurations for channels.")

        print(f"🔧 Final channel configurations loaded: {configs}")
        return configs

    def validate_required_fields(self):
        """Validates that all necessary environment variables are set."""

        # Check if .env file exists
        env_file_path = BASE_DIR / ".env"
        if not env_file_path.exists():
            raise ValueError(
                f"❌ .env file not found at {env_file_path}\n"
                f"   Please copy .env.example to .env and configure your settings:\n"
                f"   cp .env.example .env"
            )

        # Channel ID Validation
        if self.DRY_RUN:
            if not self.TELEGRAM_DRY_RUN_CHANNEL_ID:
                raise ValueError(
                    "Missing required environment variable: TELEGRAM_DRY_RUN_CHANNEL_ID (required when DRY_RUN=true)"
                )
        else:  # Live Trading
            if not self.TELEGRAM_CHANNEL_ID:
                raise ValueError(
                    "Missing required environment variable: TELEGRAM_CHANNEL_ID (required when DRY_RUN=false)"
                )

            # Live Trading API Key Validation
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

    def get_channel_start_balance(self, channel: str) -> tuple[str, float]:
        """
        Get the starting currency and amount for a specific channel.
        Returns: (currency, amount) tuple for the primary quote currency (e.g., USDT) or the first available.
        """
        channel_name = str(channel).replace('@', '')

        configs = self.channel_wallet_configurations
        if channel_name in configs:
            wallet = configs[channel_name]
            # Prioritize USDT or USDC as the primary starting balance
            for quote_currency in ["USDT", "USDC"]:
                if quote_currency in wallet:
                    return quote_currency, wallet[quote_currency]

            # If no primary quote currency, return the first one found
            if wallet:
                first_currency = next(iter(wallet))
                return first_currency, wallet[first_currency]

        # Default fallback
        return "USDT", 1000.0

    def print_channel_configurations(self):
        """Print channel configurations for debugging."""
        configs = self.channel_wallet_configurations
        if configs:
            print("📊 Channel wallet configurations:")
            for channel, wallet_config in configs.items():
                currencies = [f"{amount} {currency}" for currency, amount in wallet_config.items()]
                print(f"   📺 {channel}: {', '.join(currencies)}")
        else:
            print("📊 No custom channel configurations found, using defaults")

    def print_auto_sell_configuration(self):
        """Print auto sell monitor configuration."""
        print(f"🤖 Auto Sell Monitor: {'ENABLED' if self.AUTO_SELL_MONITOR else 'DISABLED'}")
        if self.AUTO_SELL_MONITOR:
            print("   📊 Will automatically monitor open trades every 5 minutes")
            print("   💰 Will use SellDecisionManager for intelligent sell decisions")
            print("   ⚡ Will automatically close profitable trades")
        else:
            print("   📱 Will use current behavior (manual sells from Telegram signals)")

# Create a single, global instance of the settings
# This will validate the .env file exists and load only from there
try:
    settings = Settings()
    print("✅ Settings loaded successfully from .env file")
    settings.print_auto_sell_configuration()  # Show auto sell status
except Exception as e:
    print(f"❌ Failed to load settings: {e}")
    raise