"""Updated main trading application with conditional auto-sell monitor support."""
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
from src.database import TradingDatabase
from src.take_profit_decision_manager import TakeProfitDecisionManager


# Conditional imports for auto-sell monitor
if settings.AUTO_SELL_MONITOR:
    try:
        from src.auto_sell_monitor import AutoSellMonitor
        from src.sell_decision_manager import SellDecisionManager, SellDecision
        AUTO_SELL_AVAILABLE = True
        print("🤖 Auto Sell Monitor classes loaded successfully")
    except ImportError as e:
        print(f"⚠️ Auto Sell Monitor enabled but classes not available: {e}")
        print("   Falling back to manual sell logic")
        AUTO_SELL_AVAILABLE = False
else:
    AUTO_SELL_AVAILABLE = False

# Dynamic Imports Based on Trading Mode
if settings.TRADING_MODE.upper() == "FUTURES":
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
        self.db = TradingDatabase()
        self.analyzer = SignalAnalyzer(db=self.db)
        self.trader = None
        self.auto_sell_monitor = None  # Will be initialized if enabled

        # Initialize the new Take-Profit Decision Manager (if enabled in settings)
        if self.settings.ENABLE_LLM_TP_SELECTOR:
            self.tp_manager = TakeProfitDecisionManager(self.settings, self.db)
            self.logger.info("🤖 LLM Take-Profit Selector is ENABLED")
        else:
            self.tp_manager = None
            self.logger.info(" Gunning for T3: Static Take-Profit Selector is ENABLED")

        # Directly use the channel configurations from the settings file.
        if self.settings.DRY_RUN:
            self.channel_configs = self.settings.channel_wallet_configurations
        else:
            self.channel_configs = {}

        # Instantiate the correct validator with required arguments
        if self.settings.TRADING_MODE.upper() == "FUTURES":
            self.validator = PairValidator()
        else:  # SPOT
            self.validator = PairValidator(self.settings.EXCHANGE)

        if self.settings.DRY_RUN:
            self.logger.info(f"🤖 Starting in DRY RUN mode for {self.settings.TRADING_MODE} trading.")
            self.trader = DryRunTrader(
                exchange=settings.EXCHANGE,
                trading_mode=settings.TRADING_MODE,
                db=self.db,
                channel_configs=self.channel_configs
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

        # Initialize Auto Sell Monitor if enabled
        if self.settings.AUTO_SELL_MONITOR and AUTO_SELL_AVAILABLE:
            self.auto_sell_monitor = AutoSellMonitor(
                db=self.db,
                trader=self.trader,
                settings=self.settings,
                logger=self.logger
            )
            self.logger.info("🤖 Auto Sell Monitor initialized and ready")
        elif self.settings.AUTO_SELL_MONITOR and not AUTO_SELL_AVAILABLE:
            self.logger.warning("⚠️ Auto Sell Monitor requested but not available - using manual sell logic")

        self.telegram = TelegramMonitor(
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH,
            settings.target_channels,
            self.logger
        )
        self.daily_trades = 0

        if self.settings.DRY_RUN:
            self._ensure_wallet_history_from_env()

    def _ensure_wallet_history_from_env(self):
        """
        Ensure all channels from .env CHANNEL_WALLET_CONFIGS have initial wallet history.
        """
        try:
            channel_configs = self.settings.channel_wallet_configurations

            if not channel_configs:
                self.logger.info("📊 No channel configurations found in .env")
                return

            self.logger.info("📊 Ensuring wallet history exists for all .env channels...")

            for channel_name, config in channel_configs.items():
                try:
                    if self._is_template_channel(channel_name):
                        continue

                    self.db.cursor.execute("SELECT COUNT(*) FROM wallet_history WHERE channel_name = ?", (channel_name,))
                    if self.db.cursor.fetchone()[0] == 0:
                        usd_value = sum(amount for currency, amount in config.items() if currency.upper() in ['USD', 'USDT', 'USDC'])
                        self.db.add_wallet_history_record(
                            channel_name=channel_name,
                            total_value_usd=usd_value,
                            balances=config
                        )
                        self.logger.info(f"   ✅ Created initial wallet history for '{channel_name}': {config}")
                    else:
                        self.logger.info(f"   ℹ️ Wallet history exists for '{channel_name}'")

                except Exception as e:
                    self.logger.error(f"❌ Error initializing wallet history for '{channel_name}': {e}")

        except Exception as e:
            self.logger.error(f"❌ Error in wallet history initialization from .env: {e}")

    def _is_template_channel(self, channel_name: str) -> bool:
        """Check if a channel name looks like a template."""
        if not channel_name or channel_name == 'global':
            return False
        template_patterns = ['test_channel', 'example', 'template', 'demo']
        return any(pattern in str(channel_name).lower() for pattern in template_patterns)

    async def on_message(self, message: str, channel: str):
        self.logger.info(f"Processing message from {channel}: {message[:100]}...")
        llm_response_id = None

        try:
            parsed = await self.analyzer.analyze(message, channel)
            self.logger.info(f"Parsed signal: {parsed}")
            llm_response_id = parsed.get("llm_response_id") if parsed else None

        except SignalParseError as e:
            self.logger.warning(f"Could not parse signal: {e}")
            return
        except Exception as e:
            self.logger.error(f"Unexpected error in signal analysis: {e}")
            return

        if not parsed:
            self.logger.warning("Parsed signal is None, skipping.")
            return

        if int(parsed.get("confidence", 0)) < self.settings.MIN_CONFIDENCE_THRESHOLD:
            self.logger.info(f"Signal confidence below threshold")
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
            self.logger.info(f"Validated pair: {validated_pair_str}")
        except PairNotFoundError as e:
            self.logger.warning(f"Pair not available: {e}")
            return
        except Exception as e:
            self.logger.error(f"Error validating pair: {e}")
            return

        try:
            # Get balance
            balances = await self.trader.get_balance(channel if self.settings.DRY_RUN else None)
            balance_source = f"channel '{channel}'" if self.settings.DRY_RUN else f"{self.settings.EXCHANGE} account"
            self.logger.info(f"Current balances in {balance_source}: {balances}")

            side = "buy" if parsed.get("action").lower() == "buy" else "sell"
            volume = 0.0
            original_buy_trade_id = None

            if side == "buy":
                volume = await self._calculate_buy_volume(parsed, balances, quote, validated_pair_str)
                if volume <= 0: return
            else:  # sell
                handler = self._handle_auto_monitored_sell if self.settings.AUTO_SELL_MONITOR and AUTO_SELL_AVAILABLE else self._handle_manual_sell
                volume, original_buy_trade_id = await handler(parsed, channel, base, quote, validated_pair_str, balances)
                if not volume or volume <= 0:
                    self.logger.warning("Sell conditions not met or volume is zero. Skipping sell order.")
                    return

            # --- Take-Profit Logic ---
            take_profit, take_profit_target, llm_tp_reasoning = await self._determine_take_profit(parsed, side)

            leverage = self._extract_leverage(parsed)
            targets_for_trade = parsed.get("targets")

            # The new PlaceOrder class will handle logging, so we pass all relevant data
            res = await self.trader.place_order(
                pair=validated_pair_str,
                side=side,
                volume=volume,
                ordertype=("limit" if parsed.get("entry_price") else "market"),
                price=parsed.get("entry_price"),
                telegram_channel=channel,
                take_profit=take_profit,
                stop_loss=parsed.get("stop_loss"),
                take_profit_target=take_profit_target,
                leverage=leverage,
                targets=targets_for_trade,
                llm_response_id=llm_response_id,
                llm_tp_reasoning=llm_tp_reasoning,
                original_buy_trade_id=original_buy_trade_id # Pass this for the sell logic
            )

            if res:
                self.logger.info(f"Order placement result: {res}")
                if side == "buy":
                    self.daily_trades += 1
            else:
                self.logger.error("Order placement failed. Check logs for details.")

        except InsufficientBalanceError as e:
            self.logger.warning(f"Insufficient balance to place order: {e}")
        except Exception as e:
            self.logger.exception(f"Order processing failed: {e}")

    async def _determine_take_profit(self, parsed, side):
        """Determine the take-profit price, target index, and reasoning."""
        targets = parsed.get("targets")
        if not targets:
            return None, None, None

        if side == "buy" and self.tp_manager:
            self.logger.info("🤖 Using LLM to select the best take-profit target...")
            tp_price, tp_idx, reason = await self.tp_manager.select_best_target(parsed)
            if tp_price is not None:
                self.logger.info(f"   🧠 LLM Chose Target #{tp_idx + 1} ({tp_price}). Reason: {reason}")
                return tp_price, tp_idx, reason
            self.logger.warning("   ⚠️ LLM TP selection failed, falling back to static logic.")

        # Static fallback logic
        if len(targets) >= 3:
            return targets[-3], len(targets) - 3, "Static Fallback: Chose third to last target."
        return targets[-1], 0, "Static Fallback: Chose the final target."

    def _extract_leverage(self, parsed):
        """Extracts leverage from the parsed signal."""
        if self.settings.TRADING_MODE.upper() != "FUTURES":
            return 0
        leverage_str = parsed.get("leverage")
        if leverage_str:
            match = re.search(r'(\d+)', str(leverage_str))
            if match:
                leverage = int(match.group(1))
                self.logger.info(f"Extracted leverage from signal: {leverage}x")
                return leverage
        return 0

    async def _calculate_buy_volume(self, parsed, balances, quote, validated_pair_str):
        """Calculate volume for buy orders."""
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
            return 0

        entry = parsed.get("entry_price")
        if entry is None and parsed.get("entry_price_range"):
            entry = sum(parsed.get("entry_price_range")) / 2.0

        if entry is None:
            market_price = await self.trader.get_market_price(validated_pair_str)
            volume = order_value / max(1e-8, market_price)
        else:
            volume = order_value / max(1e-8, entry)

        return volume

    async def _handle_auto_monitored_sell(self, parsed, channel, base, quote, validated_pair_str, balances):
        """Handle sell when auto-sell monitor is enabled."""
        last_buy_trade = self.db.get_last_buy_trade(channel, base, quote)

        if not last_buy_trade:
            self.logger.info(f"🤖 AUTO-SELL MODE: No previous BUY trade found for {base}/{quote} from channel '{channel}'.")
            self.logger.info(f"   ℹ️ Auto-sell monitor will handle this pair automatically when trades are opened.")
            return None, None

        current_market_price = await self.trader.get_market_price(validated_pair_str)

        if hasattr(self, 'auto_sell_monitor') and self.auto_sell_monitor:
            try:
                signal_data = {
                    'action': 'SELL', 'base_currency': base, 'quote_currency': quote,
                    'confidence': parsed.get('confidence', 85),
                    'take_profit_targets': parsed.get('targets', []), 'stop_loss': parsed.get('stop_loss')
                }
                decision, reasons, additional_data = await self.auto_sell_monitor.sell_manager.should_sell(
                    signal_data=signal_data, last_buy_trade=last_buy_trade, current_price=current_market_price
                )
                summary = self.auto_sell_monitor.sell_manager.get_decision_summary(decision, reasons, additional_data)
                self.logger.info(f"🤖 AUTO-SELL DECISION for manual sell signal: {summary}")

                if decision == SellDecision.BLOCK:
                    self.logger.info("🚫 Manual sell blocked by SellDecisionManager - auto-monitor will handle this trade")
                    return None, None
                elif decision in [SellDecision.SELL, SellDecision.PARTIAL_SELL]:
                    volume = await self.auto_sell_monitor.sell_manager.get_sell_volume(
                        decision, last_buy_trade['volume'], additional_data
                    )
                    self.logger.info(f"✅ Manual sell approved by SellDecisionManager: {volume:.8f} {base}")
                    return volume, last_buy_trade['id']
                else:
                    self.logger.info("⏳ SellDecisionManager suggests HOLD - deferring to auto-monitor")
                    return None, None

            except Exception as e:
                self.logger.error(f"❌ Error in SellDecisionManager analysis: {e}")
                volume = await self._simple_profit_check(channel, last_buy_trade, current_market_price, base, quote, balances)
                return (volume, last_buy_trade['id']) if volume else (None, None)
        else:
            volume = await self._simple_profit_check(channel, last_buy_trade, current_market_price, base, quote, balances)
            return (volume, last_buy_trade['id']) if volume else (None, None)

    async def _handle_manual_sell(self, parsed, channel, base, quote, validated_pair_str, balances):
        """Handle sell using current manual logic (when auto-sell monitor is disabled)."""
        last_buy_trade = self.db.get_last_buy_trade(channel, base, quote)

        if not last_buy_trade:
            self.logger.warning(f"No previous BUY trade found for {base}/{quote} from channel '{channel}'. Skipping SELL order.")
            return None, None

        current_market_price = await self.trader.get_market_price(validated_pair_str)
        volume = await self._simple_profit_check(channel, last_buy_trade, current_market_price, base, quote, balances)

        if volume and volume > 0:
            return volume, last_buy_trade['id']

        return None, None

    async def _simple_profit_check(self, channel, last_buy_trade, current_market_price, base, quote, balances):
        """
        Perform the current simple profit check logic using pre-fetched balances.
        """
        buy_price = last_buy_trade['price']

        if buy_price and current_market_price:
            profit_percentage = ((current_market_price - buy_price) / buy_price) * 100
            self.logger.info(f"   Profit: {profit_percentage:.2f}%")
        else:
            self.logger.warning(f"⚠️ Could not determine profit/loss - missing price data")
            return None

        # Ensure we sell the exact volume we bought to close the position
        volume_to_sell = last_buy_trade['volume']
        base_balance = balances.get(base, 0.0)

        self.logger.info(f"Required sell volume: {volume_to_sell:.8f}, current balance: {base_balance:.8f}")

        # CRITICAL: Check if we have enough balance to fully close the trade.
        # Add a small tolerance (0.1%) for floating point precision issues.
        if base_balance < (volume_to_sell * 0.999):
            self.logger.error(f"CRITICAL: Insufficient {base} balance to close the trade. "
                              f"Expected to sell {volume_to_sell:.8f}, but only have {base_balance:.8f}. "
                              f"Manual intervention may be required. Skipping automated sell.")
            return None

        self.logger.info(f"Setting SELL order volume to match last BUY: {volume_to_sell:.8f} {base}")
        return volume_to_sell

    async def run(self):
        self.logger.info("Starting trading application...")
        self.logger.info(f"Settings: MODE={self.settings.TRADING_MODE}, EXCHANGE={self.settings.EXCHANGE}, DRY_RUN={self.settings.DRY_RUN}")
        self.logger.info(f"Channels={self.settings.target_channels}, Max daily BUY trades={self.settings.MAX_DAILY_TRADES}")

        if self.settings.AUTO_SELL_MONITOR:
            status = "ENABLED" if AUTO_SELL_AVAILABLE and self.auto_sell_monitor else "REQUESTED but NOT AVAILABLE"
            self.logger.info(f"🤖 Auto Sell Monitor: {status}")
        else:
            self.logger.info(f"📱 Auto Sell Monitor: DISABLED")

        if self.settings.DRY_RUN:
            self.logger.info(f"💰 Channel-specific wallets initialized.")

        if not self.settings.DRY_RUN:
            self.logger.info(f"Performing initial balance sync from {self.settings.EXCHANGE}...")
            try:
                live_balances = await self.trader.get_balance()
                live_wallet_channel_name = f"{self.settings.EXCHANGE.upper()} (Live)"
                self.db.sync_wallet(live_balances, channel=live_wallet_channel_name)
                self.logger.info(f"✅ Live wallet balances synced with local database.")
            except Exception as e:
                self.logger.error(f"❌ CRITICAL: Failed to sync wallet balances: {e}")
                return

        auto_sell_task = None
        if self.settings.AUTO_SELL_MONITOR and AUTO_SELL_AVAILABLE and self.auto_sell_monitor:
            self.logger.info("🚀 Starting Auto Sell Monitor in background...")
            auto_sell_task = asyncio.create_task(self.auto_sell_monitor.start_monitoring())

        try:
            await self.telegram.start(self.on_message)
        except Exception as e:
            self.logger.exception(f"Error starting telegram monitor: {e}")
        finally:
            if auto_sell_task and self.auto_sell_monitor:
                self.logger.info("🛑 Stopping Auto Sell Monitor...")
                await self.auto_sell_monitor.stop_monitoring()


if __name__ == "__main__":
    app = TradingApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Shutting down")
    except Exception as e:
        logger.exception(f"Application error: {e}")