"""Main application entrypoint orchestrating all components."""
import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from config.settings import settings
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
    from src.database import TradingDatabase
    from src.kraken_trader import KrakenTrader

from src.utils.exceptions import InsufficientBalanceError, PairNotFoundError, SignalParseError

logger = setup_logger(level=settings.LOG_LEVEL)

class TradingApp:
    def __init__(self):
        self.settings = settings
        self.logger = logger
        self.analyzer = SignalAnalyzer()
        self.validator = PairValidator()
        self.db = None
        self.trader = None

        if self.settings.DRY_RUN:
            self.logger.info("🤖 Starting in DRY RUN mode. No real trades will be executed.")
            self.trader = DryRunTrader(
                settings.KRAKEN_API_KEY,
                settings.KRAKEN_API_SECRET
            )
            self.db = self.trader.db
        else:
            self.logger.info("⚡ Starting in LIVE TRADING mode. Real trades will be executed.")
            self.db = TradingDatabase()
            self.trader = KrakenTrader(
                settings.KRAKEN_API_KEY,
                settings.KRAKEN_API_SECRET,
                self.db
            )

        self.telegram = TelegramMonitor(
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            settings.target_channels,
            self.logger
        )
        self.daily_trades = 0

    async def on_message(self, message: str, channel: str):
        self.logger.info(f"Processing message from {channel}: {message[:100]}...")

        try:
            parsed = await self.analyzer.analyze(message)
            self.logger.info(f"Parsed signal: {parsed}")

            if parsed and self.db:
                try:
                    self.db.add_llm_response(parsed)
                    self.logger.info("✅ Successfully saved LLM response to the database.")
                except Exception as db_err:
                    self.logger.error(f"❌ Failed to save LLM response to database: {db_err}")

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

        try:
            balances = await self.trader.get_balance()
            self.logger.info(f"Current balances: {balances}")

            side = "buy" if parsed.get("action") == "BUY" else "sell"
            volume = 0.0

            if side == "buy":
                quote_balance = balances.get(quote, 0.0)
                order_value = 0.0

                if self.settings.ORDER_SIZE_USD > 0:
                    order_value = self.settings.ORDER_SIZE_USD
                    self.logger.info(f"Using fixed order size from settings: {order_value} {quote}")
                else:
                    max_pct = self.settings.MAX_POSITION_SIZE_PERCENT / 100.0
                    order_value = quote_balance * max_pct
                    self.logger.info(f"Calculating order size based on {self.settings.MAX_POSITION_SIZE_PERCENT}% of {quote} balance.")

                if order_value <= 0:
                    self.logger.warning(f"Calculated order value is {order_value:.2f}. Must be positive. Skipping.")
                    return

                entry = parsed.get("entry_price")
                if entry is None and parsed.get("entry_price_range"):
                    entry = sum(parsed.get("entry_price_range")) / 2.0

                if entry is None:
                    entry_for_volume_calc = await self.trader.get_market_price(f"{base}{quote}") if hasattr(self.trader, 'get_market_price') else 1.0
                    volume = order_value / max(1e-8, entry_for_volume_calc)
                else:
                    volume = order_value / max(1e-8, entry)

            else: # side == "sell"
                base_balance = balances.get(base, 0.0)
                self.logger.info(f"Detected SELL signal for {base}. Current balance: {base_balance}")
                if base_balance <= 0:
                    self.logger.warning(f"Cannot place SELL order. You have no {base} to sell.")
                    return

                volume = base_balance
                self.logger.info(f"Setting order volume to sell 100% of {base} balance: {volume:.8f}")

            pair_str = f"{base}/{quote}"
            entry = parsed.get("entry_price")
            if entry is None and parsed.get("entry_price_range"):
                entry = sum(parsed.get("entry_price_range")) / 2.0

            stop_loss = parsed.get("stop_loss")
            take_profit_levels = parsed.get("take_profit_levels")
            take_profit = None
            take_profit_key = None

            if take_profit_levels and len(take_profit_levels) >= 2:
                take_profit = take_profit_levels[-2]
                take_profit_key = len(take_profit_levels) - 2
            elif take_profit_levels:
                take_profit = take_profit_levels[-1]
                take_profit_key = 0

            self.logger.info(f"Placing order: {side} {volume:.6f} {pair_str} at {entry} from {channel}")
            self.logger.info(f"SL: {stop_loss}, TP: {take_profit} (Key: {take_profit_key})")

            res = await self.trader.place_order(
                pair_str,
                side,
                volume,
                ordertype=("limit" if entry else "market"),
                price=entry,
                telegram_channel=channel,
                take_profit=take_profit,
                stop_loss=stop_loss,
                take_profit_key=take_profit_key
            )

            self.logger.info(f"Order result: {res}")
            self.daily_trades += 1

        except InsufficientBalanceError as e:
            self.logger.warning(f"Insufficient balance to place order: {e}")
        except Exception as e:
            self.logger.exception(f"Order failed: {e}")

    async def run(self):
        self.logger.info("Starting trading application...")
        self.logger.info(f"Settings: DRY_RUN={self.settings.DRY_RUN}, Channels={self.settings.target_channels}, Max trades={self.settings.MAX_DAILY_TRADES}")

        if not self.settings.DRY_RUN:
            self.logger.info("Performing initial balance sync from Kraken...")
            try:
                live_balances = await self.trader.get_balance()
                self.db.sync_wallet(live_balances)
                self.logger.info("✅ Live wallet balances synced with local database.")
            except Exception as e:
                self.logger.error(f"❌ CRITICAL: Failed to sync wallet balances from Kraken: {e}")
                self.logger.error("   Please check your API keys and network connection. Exiting.")
                return

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