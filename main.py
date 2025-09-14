"""Main application entrypoint orchestrating all components."""
import asyncio
import sys
import os
import re

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

from src.dry_run.trader import DryRunTrader
from src.utils.exceptions import InsufficientBalanceError, PairNotFoundError, SignalParseError

if settings.DRY_RUN:
    from src.dry_run.database import DryRunDatabase as TradingDatabase
else:
    from src.database import TradingDatabase

# --- Dynamic Imports Based on Trading Mode ---
if settings.TRADING_MODE.upper() == "FUTURES":
    # For futures, we use a specific validator and MEXC's futures trader
    from src.futures.futures_pair_validator import FuturesPairValidator as PairValidator
    if not settings.DRY_RUN:
        from src.futures.mexc_futures_trader import MexcFuturesTrader as LiveTrader
else:  # SPOT trading
    from src.pair_validator import PairValidator
    if not settings.DRY_RUN:
        if settings.EXCHANGE.upper() == "KRAKEN":
            from src.kraken_trader import KrakenTrader as LiveTrader
        elif settings.EXCHANGE.upper() == "MEXC":
            from src.mexc_trader import MexcTrader as LiveTrader

logger = setup_logger(level=settings.LOG_LEVEL)

class TradingApp:
    def __init__(self):
        self.settings = settings
        self.logger = logger
        self.analyzer = SignalAnalyzer()
        self.db = TradingDatabase()
        self.trader = None

        # --- FIX: Instantiate the correct validator with required arguments ---
        if self.settings.TRADING_MODE.upper() == "FUTURES":
            self.validator = PairValidator()  # FuturesPairValidator requires no arguments
        else: # SPOT
            self.validator = PairValidator(self.settings.EXCHANGE)  # Spot PairValidator needs the exchange name

        if self.settings.DRY_RUN:
            self.logger.info(f"🤖 Starting in DRY RUN mode for {self.settings.TRADING_MODE} trading.")
            self.trader = DryRunTrader(
                exchange=settings.EXCHANGE,
                trading_mode=settings.TRADING_MODE
            )
        else:
            self.logger.info(f"⚡ Starting in LIVE {self.settings.TRADING_MODE} mode on {self.settings.EXCHANGE}.")
            if self.settings.TRADING_MODE.upper() == "FUTURES":
                self.trader = LiveTrader(
                    self.settings.MEXC_API_KEY,
                    self.settings.MEXC_API_SECRET,
                    self.db,
                    self.settings.DEFAULT_LEVERAGE
                )
            else:  # SPOT
                api_key = self.settings.KRAKEN_API_KEY if self.settings.EXCHANGE.upper() == "KRAKEN" else self.settings.MEXC_API_KEY
                api_secret = self.settings.KRAKEN_API_SECRET if self.settings.EXCHANGE.upper() == "KRAKEN" else self.settings.MEXC_API_SECRET
                self.trader = LiveTrader(api_key, api_secret, self.db)

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
            parsed = await self.analyzer.analyze(message, channel)
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

        if parsed is None:
            self.logger.warning("Parsed signal is None, skipping.")
            return
        conf = parsed.get("confidence", 0) or 0
        if conf < self.settings.MIN_CONFIDENCE_THRESHOLD:
            self.logger.info(f"Signal confidence {conf} below threshold {self.settings.MIN_CONFIDENCE_THRESHOLD}")
            return

        if self.daily_trades >= self.settings.MAX_DAILY_TRADES:
            self.logger.warning("Max daily trades reached")
            return

        base = parsed.get("base_currency")
        quote = parsed.get("quote_currency") or "USDT"

        if not base:
            self.logger.warning("No base currency found in signal")
            return

        try:
            validated_pair_str, base, quote = await self.validator.validate_and_convert(base, quote)
            self.logger.info(f"Validated pair for {self.settings.EXCHANGE} ({self.settings.TRADING_MODE}): {validated_pair_str} ({base}/{quote})")
        except PairNotFoundError as e:
            self.logger.warning(f"Pair not available on {self.settings.EXCHANGE}: {e}")
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
                    market_price = await self.trader.get_market_price(validated_pair_str)
                    volume = order_value / max(1e-8, market_price)
                else:
                    volume = order_value / max(1e-8, entry)

            else:  # side == "sell"
                # Check for last buy trade from the same channel
                last_buy_trade = self.db.get_last_buy_trade(channel, base, quote)

                if not last_buy_trade:
                    self.logger.warning(f"No previous BUY trade found for {base}/{quote} from channel '{channel}'. Skipping SELL order.")
                    return

                # Use the volume from the last buy trade
                volume = last_buy_trade['volume']
                base_balance = balances.get(base, 0.0)

                self.logger.info(f"Found last BUY trade from '{channel}' for {base}: volume={volume:.8f}, current balance={base_balance:.8f}")

                # Check if we have enough balance to sell
                if base_balance < volume:
                    self.logger.warning(f"Insufficient {base} balance to sell {volume:.8f}. Available: {base_balance:.8f}. Will sell available amount.")
                    volume = base_balance

                if volume <= 0:
                    self.logger.warning(f"No {base} available to sell. Skipping.")
                    return

                self.logger.info(f"Setting SELL order volume to match last BUY from '{channel}': {volume:.8f} {base}")

            entry = parsed.get("entry_price")
            if entry is None and parsed.get("entry_price_range"):
                entry = sum(parsed.get("entry_price_range")) / 2.0

            stop_loss = parsed.get("stop_loss")
            take_profit_targets = parsed.get("take_profit_targets")
            take_profit = None
            take_profit_target = None

            if take_profit_targets and len(take_profit_targets) >= 3:
                take_profit = take_profit_targets[-3]
                take_profit_target = len(take_profit_targets) - 3
            elif take_profit_targets:
                take_profit = take_profit_targets[-1]
                take_profit_target = 0

            # --- Futures Specific Logic ---
            leverage = 0
            if self.settings.TRADING_MODE.upper() == "FUTURES":
                leverage_str = parsed.get("leverage")
                if leverage_str:
                    # Extracts numbers from strings like "Cross 20x"
                    leverage_digits = re.search(r'(\d+)', str(leverage_str))
                    if leverage_digits:
                        leverage = int(leverage_digits.group(1))
                        self.logger.info(f"Extracted leverage from signal: {leverage}x")

            self.logger.info(f"Placing order: {side} {volume:.6f} {validated_pair_str} at {entry} from {channel}")
            self.logger.info(f"SL: {stop_loss}, TP: {take_profit} (Key: {take_profit_target}), Leverage: {leverage or 'Default'}x")

            # The 'leverage' kwarg will be safely ignored by spot traders
            res = await self.trader.place_order(
                pair=validated_pair_str,
                side=side,
                volume=volume,
                ordertype=("limit" if entry else "market"),
                price=entry,
                telegram_channel=channel,
                take_profit=take_profit,
                stop_loss=stop_loss,
                take_profit_target=take_profit_target,
                leverage=leverage
            )

            self.logger.info(f"Order result: {res}")
            self.daily_trades += 1

        except InsufficientBalanceError as e:
            self.logger.warning(f"Insufficient balance to place order: {e}")
        except Exception as e:
            self.logger.exception(f"Order failed: {e}")

    async def run(self):
        self.logger.info("Starting trading application...")
        self.logger.info(f"Settings: MODE={self.settings.TRADING_MODE}, EXCHANGE={self.settings.EXCHANGE}, DRY_RUN={self.settings.DRY_RUN}, Channels={self.settings.target_channels}, Max daily BUY trades={self.settings.MAX_DAILY_TRADES}")

        if not self.settings.DRY_RUN:
            self.logger.info(f"Performing initial balance sync from {self.settings.EXCHANGE}...")
            try:
                live_balances = await self.trader.get_balance()
                self.db.sync_wallet(live_balances)
                self.logger.info("✅ Live wallet balances synced with local database.")
            except Exception as e:
                self.logger.error(f"❌ CRITICAL: Failed to sync wallet balances from {self.settings.EXCHANGE}: {e}")
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