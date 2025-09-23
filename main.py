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
        self.analyzer = SignalAnalyzer()
        self.db = TradingDatabase()
        self.trader = None
        self.auto_sell_monitor = None  # Will be initialized if enabled

        # Directly use the channel configurations from the settings file.
        # This correctly loads and respects the CHANNEL_WALLET_CONFIGS from your .env file.
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
                channel_configs=self.channel_configs # Pass the correctly loaded configs
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
            # Get channel configurations directly from settings
            channel_configs = self.settings.channel_wallet_configurations

            if not channel_configs:
                self.logger.info("📊 No channel configurations found in .env")
                return

            self.logger.info("📊 Ensuring wallet history exists for all .env channels...")

            for channel_name, config in channel_configs.items():
                try:
                    # Skip template channels
                    if self._is_template_channel(channel_name):
                        continue

                    # Check if wallet history exists for this channel
                    self.db.cursor.execute("""
                            SELECT COUNT(*) FROM wallet_history 
                            WHERE channel_name = ?
                        """, (channel_name,))

                    existing_count = self.db.cursor.fetchone()[0]

                    if existing_count == 0:
                        # The 'config' variable is the initial balances dictionary
                        initial_balances = config

                        # Convert to USD equivalent (simplified, assumes USDT/USDC are 1:1 with USD)
                        usd_value = 0.0
                        for currency, amount in initial_balances.items():
                            if currency.upper() in ['USD', 'USDT', 'USDC']:
                                usd_value += amount
                            # Note: a more complex calculation would fetch live prices for non-USD assets

                        self.db.add_wallet_history_record(
                            channel_name=channel_name,
                            total_value_usd=usd_value, # Use the calculated USD value
                            balances=initial_balances
                        )

                        self.logger.info(
                            f"   ✅ Created initial wallet history for '{channel_name}': {initial_balances}")
                    else:
                        self.logger.info(
                            f"   ℹ️  Wallet history exists for '{channel_name}' ({existing_count} records)")

                except Exception as e:
                    self.logger.error(f"❌ Error initializing wallet history for '{channel_name}': {e}")

        except Exception as e:
            self.logger.error(f"❌ Error in wallet history initialization from .env: {e}")

    def _is_template_channel(self, channel_name: str) -> bool:
        """Check if a channel name looks like a template."""
        if not channel_name or channel_name == 'global':
            return False
        template_patterns = ['test_channel', 'example', 'template', 'demo']
        channel_lower = str(channel_name)
        return any(pattern in channel_lower for pattern in template_patterns)

    async def on_message(self, message: str, channel: str):
        self.logger.info(f"Processing message from {channel}: {message[:100]}...")

        try:
            parsed = await self.analyzer.analyze(message, channel)
            self.logger.info(f"Parsed signal: {parsed}")

            if parsed and self.db:
                try:
                    self.db.add_llm_response(parsed, channel)
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
            # Get channel-specific balance if in dry run mode
            if self.settings.DRY_RUN:
                balances = await self.trader.get_balance(channel)
                balance_source = f"channel '{channel}'"

                # Auto-initialize channel if it doesn't exist
                if not balances:
                    self.logger.info(f"🔧 Initializing wallet for new channel: {channel}")
                    if hasattr(self.trader.wallet, 'initialize_channel_if_needed'):
                        self.trader.wallet.initialize_channel_if_needed(channel)
                        balances = await self.trader.get_balance(channel)
            else:
                balances = await self.trader.get_balance()
                balance_source = f"{self.settings.EXCHANGE} account"

            self.logger.info(f"Current balances in {balance_source}: {balances}")

            side = "buy" if parsed.get("action") == "BUY" else "sell"
            volume = 0.0

            if side == "buy":
                volume = await self._calculate_buy_volume(parsed, balances, quote, validated_pair_str)
                if volume <= 0:
                    return

            else:  # side == "sell"
                # Handle sell logic based on AUTO_SELL_MONITOR setting
                if self.settings.AUTO_SELL_MONITOR and AUTO_SELL_AVAILABLE:
                    # When auto-sell monitor is enabled, we generally skip manual sells
                    # unless it's a forced sell or the auto monitor decides it's appropriate
                    sell_result = await self._handle_auto_monitored_sell(parsed, channel, base, quote, validated_pair_str, balances)
                    if not sell_result:
                        return
                    volume = sell_result
                else:
                    # Use current manual sell logic
                    sell_result = await self._handle_manual_sell(parsed, channel, base, quote, validated_pair_str, balances)
                    if not sell_result:
                        return
                    volume = sell_result

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

            # Futures Specific Logic
            leverage = 0
            if self.settings.TRADING_MODE.upper() == "FUTURES":
                leverage_str = parsed.get("leverage")
                if leverage_str:
                    leverage_digits = re.search(r'(\d+)', str(leverage_str))
                    if leverage_digits:
                        leverage = int(leverage_digits.group(1))
                        self.logger.info(f"Extracted leverage from signal: {leverage}x")

            self.logger.info(f"Placing order: {side} {volume:.6f} {validated_pair_str} at {entry} from {channel}")
            self.logger.info(f"SL: {stop_loss}, TP: {take_profit} (Key: {take_profit_target}), Leverage: {leverage or 'Default'}x")
            self.logger.info(f"💰 Using balance from: {balance_source}")

            # Place the order (leverage kwarg will be safely ignored by spot traders)
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
        # Check for last buy trade from the same channel
        last_buy_trade = self.db.get_last_buy_trade(channel, base, quote)

        if not last_buy_trade:
            self.logger.info(f"🤖 AUTO-SELL MODE: No previous BUY trade found for {base}/{quote} from channel '{channel}'.")
            self.logger.info(f"   ℹ️ Auto-sell monitor will handle this pair automatically when trades are opened.")
            return None

        # Get current market price for analysis
        current_market_price = await self.trader.get_market_price(validated_pair_str)
        buy_price = last_buy_trade['price']

        # Use SellDecisionManager to decide if manual sell should proceed
        if hasattr(self, 'auto_sell_monitor') and self.auto_sell_monitor:
            try:
                # Prepare signal data for decision
                signal_data = {
                    'action': 'SELL',
                    'base_currency': base,
                    'quote_currency': quote,
                    'confidence': parsed.get('confidence', 85),
                    'take_profit_targets': parsed.get('take_profit_targets', []),
                    'stop_loss': parsed.get('stop_loss')
                }

                # Get sell decision from SellDecisionManager
                decision, reasons, additional_data = await self.auto_sell_monitor.sell_manager.should_sell(
                    signal_data=signal_data,
                    last_buy_trade=last_buy_trade,
                    current_price=current_market_price
                )

                # Log the decision
                summary = self.auto_sell_monitor.sell_manager.get_decision_summary(decision, reasons, additional_data)
                self.logger.info(f"🤖 AUTO-SELL DECISION for manual sell signal: {summary}")

                if decision == SellDecision.BLOCK:
                    self.logger.info("🚫 Manual sell blocked by SellDecisionManager - auto-monitor will handle this trade")
                    return None
                elif decision in [SellDecision.SELL, SellDecision.PARTIAL_SELL]:
                    # Calculate sell volume using decision manager
                    volume = await self.auto_sell_monitor.sell_manager.get_sell_volume(
                        decision, last_buy_trade['volume'], additional_data
                    )
                    self.logger.info(f"✅ Manual sell approved by SellDecisionManager: {volume:.8f} {base}")
                    return volume
                else:
                    self.logger.info("⏳ SellDecisionManager suggests HOLD - deferring to auto-monitor")
                    return None

            except Exception as e:
                self.logger.error(f"❌ Error in SellDecisionManager analysis: {e}")
                # Fall back to simple profit check
                return await self._simple_profit_check(last_buy_trade, current_market_price, base, quote)
        else:
            # Auto-sell monitor not available, use simple profit check
            return await self._simple_profit_check(last_buy_trade, current_market_price, base, quote)

    async def _handle_manual_sell(self, parsed, channel, base, quote, validated_pair_str, balances):
        """Handle sell using current manual logic (when auto-sell monitor is disabled)."""
        # Check for last buy trade from the same channel
        last_buy_trade = self.db.get_last_buy_trade(channel, base, quote)

        if not last_buy_trade:
            self.logger.warning(f"No previous BUY trade found for {base}/{quote} from channel '{channel}'. Skipping SELL order.")
            return None

        # Get current market price for profit check
        current_market_price = await self.trader.get_market_price(validated_pair_str)

        return await self._simple_profit_check(last_buy_trade, current_market_price, base, quote)

    async def _simple_profit_check(self, last_buy_trade, current_market_price, base, quote):
        """Perform the current simple profit check logic."""
        buy_price = last_buy_trade['price']

        # Profit check
        if buy_price and current_market_price:
            profit_percentage = ((current_market_price - buy_price) / buy_price) * 100

            self.logger.info(f"   Buy price: {buy_price:.8f} {quote}")
            self.logger.info(f"   Current price: {current_market_price:.8f} {quote}")
            self.logger.info(f"   Profit: {profit_percentage:.2f}%")
        else:
            self.logger.warning(f"⚠️  Could not determine profit/loss - missing price data")
            self.logger.warning(f"🚫 SELL BLOCKED - Cannot verify profitability")
            return None

        # Use the volume from the last buy trade
        volume = last_buy_trade['volume']
        base_balance = self.trader.get_balance().get(base, 0.0) if hasattr(self.trader, 'get_balance') else 0.0

        self.logger.info(f"Found last BUY trade for {base}: volume={volume:.8f}, current balance={base_balance:.8f}")

        # Check if we have enough balance to sell
        if base_balance < volume:
            self.logger.warning(f"Insufficient {base} balance to sell {volume:.8f}. Available: {base_balance:.8f}. Will sell available amount.")
            volume = base_balance

        if volume <= 0:
            self.logger.warning(f"No {base} available to sell. Skipping.")
            return None

        self.logger.info(f"Setting SELL order volume to match last BUY: {volume:.8f} {base}")
        return volume

    async def run(self):
        self.logger.info("Starting trading application...")
        self.logger.info(f"Settings: MODE={self.settings.TRADING_MODE}, EXCHANGE={self.settings.EXCHANGE}, DRY_RUN={self.settings.DRY_RUN}")
        self.logger.info(f"Channels={self.settings.target_channels}, Max daily BUY trades={self.settings.MAX_DAILY_TRADES}")

        # Log auto-sell monitor status
        if self.settings.AUTO_SELL_MONITOR:
            if AUTO_SELL_AVAILABLE and self.auto_sell_monitor:
                self.logger.info(f"🤖 Auto Sell Monitor: ENABLED")
                self.logger.info(f"   📊 Will monitor open trades every 5 minutes")
                self.logger.info(f"   💰 Manual sells will be filtered through SellDecisionManager")
            else:
                self.logger.warning(f"⚠️ Auto Sell Monitor: REQUESTED but NOT AVAILABLE")
                self.logger.info(f"   📱 Using current manual sell logic as fallback")
        else:
            self.logger.info(f"📱 Auto Sell Monitor: DISABLED - using current manual sell logic")

        if self.settings.DRY_RUN:
            self.logger.info(f"💰 Channel-specific wallets initialized with configurations:")
            for channel, config in self.channel_configs.items():
                currencies = [f"{amount} {currency}" for currency, amount in config.items()]
                self.logger.info(f"   📺 {channel}: {', '.join(currencies)}")

        if not self.settings.DRY_RUN:
            self.logger.info(f"Performing initial balance sync from {self.settings.EXCHANGE}...")
            try:
                live_balances = await self.trader.get_balance()

                # Create a specific channel name for the live exchange wallet
                live_wallet_channel_name = f"{self.settings.EXCHANGE.upper()} (Live)"
                self.db.sync_wallet(live_balances, channel=live_wallet_channel_name)
                self.logger.info(f"✅ Live wallet balances for '{live_wallet_channel_name}' synced with local database.")
            except Exception as e:
                self.logger.error(f"❌ CRITICAL: Failed to sync wallet balances from {self.settings.EXCHANGE}: {e}")
                self.logger.error("   Please check your API keys and network connection. Exiting.")
                return

        # Start auto-sell monitor if enabled and available
        auto_sell_task = None
        if self.settings.AUTO_SELL_MONITOR and AUTO_SELL_AVAILABLE and self.auto_sell_monitor:
            self.logger.info("🚀 Starting Auto Sell Monitor in background...")
            auto_sell_task = asyncio.create_task(self.auto_sell_monitor.start_monitoring())

        try:
            await self.telegram.start(self.on_message)
        except Exception as e:
            self.logger.exception(f"Error starting telegram monitor: {e}")
        finally:
            # Stop auto-sell monitor if it was started
            if auto_sell_task and self.auto_sell_monitor:
                self.logger.info("🛑 Stopping Auto Sell Monitor...")
                await self.auto_sell_monitor.stop_monitoring()
                auto_sell_task.cancel()
                try:
                    await auto_sell_task
                except asyncio.CancelledError:
                    pass


if __name__ == "__main__":
    app = TradingApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Shutting down")
    except Exception as e:
        logger.exception(f"Application error: {e}")