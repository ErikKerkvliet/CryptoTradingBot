"""Main application entrypoint orchestrating all components."""
import asyncio
import sys
import os

# Ensure we can import from the project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from config.settings import settings
    # Validate that all required fields are present
    settings.validate_required_fields()
except Exception as e:
    print(f"❌ Configuration error: {e}")
    print("Please check your .env file and ensure all required variables are set.")
    sys.exit(1)

from src.utils.logger import setup_logger
from src.telegram_monitor import TelegramMonitor
from src.signal_analyzer import SignalAnalyzer
from src.pair_validator import PairValidator

if settings.DRY_RUN:
    from src.dry_run.trader import DryRunTrader
else:
    from src.kraken_trader import KrakenTrader

from src.utils.exceptions import InsufficientBalanceError, PairNotFoundError, SignalParseError

logger = setup_logger(level=settings.LOG_LEVEL)

class TradingApp:
    def __init__(self):
        self.settings = settings
        self.logger = logger
        self.analyzer = SignalAnalyzer(settings.OPENAI_API_KEY)
        self.validator = PairValidator()

        if self.settings.DRY_RUN:
            self.trader = DryRunTrader(
                settings.KRAKEN_API_KEY,
                settings.KRAKEN_API_SECRET
            )
        else:
            self.trader = KrakenTrader(
                settings.KRAKEN_API_KEY,
                settings.KRAKEN_API_SECRET,
                dry_run=self.settings.DRY_RUN
            )

        self.telegram = TelegramMonitor(
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            settings.TELEGRAM_CHANNEL_ID,
            self.logger
        )
        self.daily_trades = 0

    async def on_message(self, message: str):
        self.logger.info(f"Processing message: {message[:100]}...")

        try:
            parsed = await self.analyzer.analyze(message)
            self.logger.info(f"Parsed signal: {parsed}")
        except SignalParseError as e:
            self.logger.warning(f"Could not parse signal: {e}")
            return
        except Exception as e:
            self.logger.error(f"Unexpected error in signal analysis: {e}")
            return

        conf = parsed.get("confidence", 0) or 0
        if conf < self.settings.MIN_CONFIDENCE_THRESHOLD:
            self.logger.info(f"Signal confidence {conf} below threshold {self.settings.MIN_CONFIDENCE_THRESHOLD}")
            return

        if self.daily_trades >= self.settings.MAX_DAILY_TRADES:
            self.logger.warning("Max daily trades reached")
            return

        base = parsed.get("base_currency")
        quote = parsed.get("quote_currency") or "USDC"

        if not base:
            self.logger.warning("No base currency found in signal")
            return

        try:
            base, quote = await self.validator.validate_and_convert(base, quote)
            self.logger.info(f"Validated pair: {base}/{quote}")
        except PairNotFoundError as e:
            self.logger.warning(f"Pair not available on Kraken: {e}")
            return
        except Exception as e:
            self.logger.error(f"Error validating pair: {e}")
            return

        # compute position size
        try:
            balances = await self.trader.get_balance()
            self.logger.info(f"Current balances: {balances}")
            quote_balance = balances.get(quote) or balances.get(quote + "S") or 0.0

            # Check if a fixed order size is set in the settings
            if self.settings.ORDER_SIZE_USD > 0:
                order_value = self.settings.ORDER_SIZE_USD
                self.logger.info(f"Using fixed order size from settings: {order_value} {quote}")
            else:
                # If not, fall back to the percentage-based calculation
                max_pct = self.settings.MAX_POSITION_SIZE_PERCENT / 100.0
                order_value = quote_balance * max_pct
                self.logger.info(
                    f"Calculating order size based on {self.settings.MAX_POSITION_SIZE_PERCENT}% of balance.")

            # Safety check: ensure the calculated order value does not exceed available balance
            if order_value > quote_balance:
                self.logger.warning(
                    f"Order value of {order_value:.2f} {quote} exceeds available balance of {quote_balance:.2f}. Skipping trade.")
                return

            if order_value <= 0:
                self.logger.warning(
                    f"Order value is {order_value:.2f}. Must be positive to place a trade. {quote} balance: {quote_balance:.2f}")
                return

            # approximate volume
            entry = parsed.get("entry_price")
            if entry is None and parsed.get("entry_price_range"):
                entry = sum(parsed.get("entry_price_range")) / 2.0
            if entry is None:
                self.logger.info("No entry given; placing market order using estimated market price")
                entry = 1.0  # fallback

            volume = order_value / max(1e-8, entry)
            pair_str = f"{base}/{quote}"
            side = "buy" if parsed.get("action") == "BUY" else "sell"

            self.logger.info(f"Placing order: {side} {volume} {pair_str} at {entry}")

            res = await self.trader.place_order(
                pair_str,
                side.upper(),
                volume,
                ordertype=("limit" if parsed.get("entry_price") else "market"),
                price=entry if parsed.get("entry_price") else None
            )

            self.logger.info(f"Order result: {res}")

            if not self.settings.DRY_RUN:
                self.daily_trades += 1

        except InsufficientBalanceError as e:
            self.logger.warning(f"Insufficient balance to place order: {e}")
        except Exception as e:
            self.logger.exception(f"Order failed: {e}")

    async def run(self):
        self.logger.info("Starting trading application...")
        self.logger.info(f"Settings: DRY_RUN={self.settings.DRY_RUN}, "
                        f"Channel={self.settings.TELEGRAM_CHANNEL_ID}, "
                        f"Max trades={self.settings.MAX_DAILY_TRADES}")

        try:
            await self.telegram.start(self.on_message)
        except Exception as e:
            self.logger.exception(f"Error starting telegram monitor: {e}")

if __name__ == "__main__":
    app = TradingApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Shutting down")
    except Exception as e:
        logger.exception(f"Application error: {e}")