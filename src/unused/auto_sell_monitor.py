"""
Auto Sell Monitor - Automatically monitors open trades and executes sells based on market conditions.

This class fetches current prices from MEXC every 5 minutes for all open trades,
uses SellDecisionManager to determine if sells should be executed, and automatically
closes matching trades by selling the same volume that was bought.
"""
import asyncio
import httpx
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass

# Import the SellDecisionManager and related enums
from .sell_decision_manager import SellDecisionManager, SellDecision, SellReason


@dataclass
class OpenTrade:
    """Represents an open trade that needs monitoring."""
    trade_id: int
    base_currency: str
    quote_currency: str
    pair: str
    volume: float
    buy_price: float
    timestamp: datetime
    telegram_channel: str
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    leverage: int = 0


@dataclass
class PriceData:
    """Current price data for a trading pair."""
    pair: str
    price: float
    timestamp: datetime
    volume_24h: Optional[float] = None
    price_change_24h: Optional[float] = None


class AutoSellMonitor:
    """
    Automatically monitors open trades and executes sells based on market analysis.

    Features:
    - Fetches prices from MEXC every 5 minutes
    - Uses SellDecisionManager for intelligent sell decisions
    - Automatically closes trades by selling exact buy volume
    - Updates trade status to 'closed' after execution
    - Supports both dry-run and live trading modes
    """

    def __init__(self, db, trader, settings=None, logger=None):
        """
        Initialize the AutoSellMonitor.

        Args:
            db: Database instance for trade management
            trader: Trader instance (DryRunTrader or live trader)
            settings: Configuration settings
            logger: Logger instance
        """
        self.db = db
        self.trader = trader
        self.settings = settings
        self.logger = logger or logging.getLogger(__name__)

        # Initialize sell decision manager
        self.sell_manager = SellDecisionManager(settings)

        # HTTP client for MEXC API calls
        self.http_client = httpx.AsyncClient(timeout=10)

        # Monitoring configuration
        self.monitor_interval = 300  # 5 minutes in seconds
        self.max_api_calls_per_minute = 10  # Rate limiting

        # Internal state
        self.is_running = False
        self.open_trades: Dict[int, OpenTrade] = {}
        self.price_cache: Dict[str, PriceData] = {}
        self.last_price_fetch = datetime.min

        # Statistics
        self.stats = {
            'monitoring_cycles': 0,
            'prices_fetched': 0,
            'sells_executed': 0,
            'trades_closed': 0,
            'api_errors': 0,
            'started_at': None
        }

    async def start_monitoring(self):
        """Start the automatic monitoring process."""
        if self.is_running:
            self.logger.warning("AutoSellMonitor is already running")
            return

        self.is_running = True
        self.stats['started_at'] = datetime.now()

        self.logger.info("🤖 Starting AutoSellMonitor...")
        self.logger.info(f"   📊 Monitor interval: {self.monitor_interval} seconds")
        self.logger.info(f"   💹 Exchange: MEXC")
        self.logger.info(f"   🎯 Mode: {'DRY RUN' if self._is_dry_run() else 'LIVE TRADING'}")

        try:
            while self.is_running:
                await self._monitoring_cycle()

                # Wait for next cycle
                if self.is_running:
                    await asyncio.sleep(self.monitor_interval)

        except Exception as e:
            self.logger.error(f"❌ AutoSellMonitor crashed: {e}")
            raise
        finally:
            await self.stop_monitoring()

    async def stop_monitoring(self):
        """Stop the monitoring process and cleanup."""
        if not self.is_running:
            return

        self.is_running = False
        self.logger.info("🛑 Stopping AutoSellMonitor...")

        try:
            await self.http_client.aclose()
        except Exception as e:
            self.logger.error(f"Error closing HTTP client: {e}")

        # Log final statistics
        self._log_final_stats()

    async def _monitoring_cycle(self):
        """Execute one complete monitoring cycle."""
        cycle_start = datetime.now()
        self.stats['monitoring_cycles'] += 1

        try:
            # 1. Load open trades from database
            open_trades_count = await self._load_open_trades()

            if not self.open_trades:
                self.logger.debug("📊 No open trades to monitor")
                return

            # 2. Fetch current prices for all pairs
            prices_fetched = await self._fetch_current_prices()

            # 3. Analyze each trade for sell opportunities
            sells_executed = 0
            for trade_id, trade in list(self.open_trades.items()):
                try:
                    sell_executed = await self._analyze_and_execute_sell(trade)
                    if sell_executed:
                        sells_executed += 1
                        # Remove from monitoring after successful sell
                        del self.open_trades[trade_id]

                except Exception as e:
                    self.logger.error(f"❌ Error analyzing trade {trade_id}: {e}")

            # 4. Log cycle summary
            cycle_duration = (datetime.now() - cycle_start).total_seconds()
            self.logger.info(
                f"📊 Monitoring cycle #{self.stats['monitoring_cycles']} completed "
                f"({cycle_duration:.1f}s) - Trades: {open_trades_count}, "
                f"Prices: {prices_fetched}, Sells: {sells_executed}"
            )

        except Exception as e:
            self.logger.error(f"❌ Error in monitoring cycle: {e}")
            self.stats['api_errors'] += 1

    async def _load_open_trades(self) -> int:
        """Load open trades from database."""
        try:
            # Get all open trades (status = 'open' or 'simulated_open')
            if hasattr(self.db, 'cursor'):
                self.db.cursor.execute("""
                    SELECT id, base_currency, quote_currency, telegram_channel, 
                           volume, price, timestamp, take_profit, stop_loss, leverage
                    FROM trades 
                    WHERE status IN ('open', 'simulated_open') 
                    AND side = 'buy'
                    ORDER BY timestamp DESC
                """)

                rows = self.db.cursor.fetchall()

                # Clear current open trades
                self.open_trades.clear()

                for row in rows:
                    trade_id, base, quote, channel, volume, price, timestamp_str, tp, sl, leverage = row

                    # Parse timestamp
                    try:
                        if isinstance(timestamp_str, str):
                            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        else:
                            timestamp = timestamp_str
                    except Exception:
                        timestamp = datetime.now()

                    # Create trading pair string
                    pair = f"{base}{quote}"  # MEXC format (BTCUSDT)

                    trade = OpenTrade(
                        trade_id=trade_id,
                        base_currency=base,
                        quote_currency=quote,
                        pair=pair,
                        volume=volume,
                        buy_price=price or 0,
                        timestamp=timestamp.replace(tzinfo=None),
                        telegram_channel=channel or '',
                        take_profit=tp,
                        stop_loss=sl,
                        leverage=leverage or 0
                    )

                    self.open_trades[trade_id] = trade

                return len(self.open_trades)

        except Exception as e:
            self.logger.error(f"❌ Error loading open trades: {e}")
            return 0

    async def _fetch_current_prices(self) -> int:
        """Fetch current prices for all unique pairs from MEXC."""
        if not self.open_trades:
            return 0

        # Get unique pairs to minimize API calls
        unique_pairs = set(trade.pair for trade in self.open_trades.values())

        prices_fetched = 0

        try:
            # Use MEXC bulk price endpoint
            url = "https://api.mexc.com/api/v3/ticker/24hr"

            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()

            # Process price data
            for item in data:
                symbol = item.get('symbol', '')
                if symbol in unique_pairs:
                    try:
                        price_data = PriceData(
                            pair=symbol,
                            price=float(item.get('lastPrice', 0)),
                            timestamp=datetime.now(),
                            volume_24h=float(item.get('volume', 0)),
                            price_change_24h=float(item.get('priceChangePercent', 0))
                        )

                        self.price_cache[symbol] = price_data
                        prices_fetched += 1

                    except (ValueError, TypeError) as e:
                        self.logger.warning(f"⚠️ Invalid price data for {symbol}: {e}")

            self.stats['prices_fetched'] += prices_fetched
            self.last_price_fetch = datetime.now()

            return prices_fetched

        except Exception as e:
            self.logger.error(f"❌ Error fetching prices from MEXC: {e}")
            self.stats['api_errors'] += 1
            return 0

    async def _analyze_and_execute_sell(self, trade: OpenTrade) -> bool:
        """Analyze a trade and execute sell if conditions are met."""
        try:
            # Get current price
            price_data = self.price_cache.get(trade.pair)
            if not price_data:
                self.logger.warning(f"⚠️ No price data for {trade.pair}")
                return False

            current_price = price_data.price
            if current_price <= 0:
                self.logger.warning(f"⚠️ Invalid price for {trade.pair}: {current_price}")
                return False

            # Prepare signal data for sell decision manager
            signal_data = {
                'action': 'SELL',
                'base_currency': trade.base_currency,
                'quote_currency': trade.quote_currency,
                'confidence': 85,  # Default confidence for auto-sells
                'take_profit_targets': [trade.take_profit] if trade.take_profit else [],
                'stop_loss': trade.stop_loss
            }

            # Prepare last buy trade data
            last_buy_trade = {
                'id': trade.trade_id,
                'price': trade.buy_price,
                'volume': trade.volume,
                'timestamp': trade.timestamp,
                'telegram_channel': trade.telegram_channel
            }

            # Prepare market data
            market_data = {
                'volatility_24h': abs(price_data.price_change_24h or 0),
                'volume_change_24h': 0,  # Could be calculated if historical data available
                'trend': 'bullish' if (price_data.price_change_24h or 0) > 0 else 'bearish'
            }

            # Get sell decision
            decision, reasons, additional_data = await self.sell_manager.should_sell(
                signal_data=signal_data,
                last_buy_trade=last_buy_trade,
                current_price=current_price,
                market_data=market_data
            )

            # Log decision
            summary = self.sell_manager.get_decision_summary(decision, reasons, additional_data)
            self.logger.info(f"🔍 Trade #{trade.trade_id} ({trade.pair}): {summary}")

            # Execute sell if approved
            if decision in [SellDecision.SELL, SellDecision.PARTIAL_SELL]:
                return await self._execute_sell_order(trade, decision, additional_data)

            return False

        except Exception as e:
            self.logger.error(f"❌ Error analyzing trade {trade.trade_id}: {e}")
            return False

    async def _execute_sell_order(
            self,
            trade: OpenTrade,
            decision: SellDecision,
            additional_data: Dict[str, Any]
    ) -> bool:
        """Execute the sell order and update trade status."""
        try:
            # Calculate sell volume
            if decision == SellDecision.SELL:
                sell_volume = trade.volume  # Sell full amount
            else:  # PARTIAL_SELL
                sell_volume = await self.sell_manager.get_sell_volume(
                    decision, trade.volume, additional_data
                )

            if sell_volume <= 0:
                self.logger.warning(f"⚠️ Invalid sell volume calculated: {sell_volume}")
                return False

            # Get current price for the sell
            price_data = self.price_cache.get(trade.pair)
            current_price = price_data.price if price_data else None

            # Execute sell order through trader
            order_result = await self.trader.place_order(
                pair=f"{trade.base_currency}/{trade.quote_currency}",  # Format for trader
                side="sell",
                volume=sell_volume,
                ordertype="market",
                price=current_price,
                telegram_channel=trade.telegram_channel,
                # Add reference to original buy trade
                original_trade_id=trade.trade_id
            )

            # Update original trade status to closed
            await self._update_trade_status(trade.trade_id, 'closed', sell_volume, current_price)

            # Calculate profit
            profit = (current_price - trade.buy_price) * sell_volume if current_price else 0
            profit_pct = ((
                                      current_price - trade.buy_price) / trade.buy_price) * 100 if current_price and trade.buy_price > 0 else 0

            self.logger.info(
                f"✅ SELL EXECUTED - Trade #{trade.trade_id} ({trade.pair}): "
                f"{sell_volume:.8f} at {current_price:.8f} "
                f"(Profit: {profit:+.8f} {trade.quote_currency}, {profit_pct:+.2f}%)"
            )

            self.stats['sells_executed'] += 1
            self.stats['trades_closed'] += 1

            return True

        except Exception as e:
            self.logger.error(f"❌ Error executing sell for trade {trade.trade_id}: {e}")
            return False

    async def _update_trade_status(
            self,
            trade_id: int,
            new_status: str,
            sell_volume: float,
            sell_price: Optional[float]
    ):
        """Update trade status in database."""
        try:
            if hasattr(self.db, 'cursor'):
                # Update the original buy trade status
                self.db.cursor.execute("""
                    UPDATE trades 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (new_status, trade_id))

                # Add a note about the auto-sell
                self.db.cursor.execute("""
                    UPDATE trades 
                    SET ordertype = ordertype || ' (auto-closed)'
                    WHERE id = ?
                """, (trade_id,))

                self.db.conn.commit()

                self.logger.debug(f"📝 Updated trade {trade_id} status to '{new_status}'")

        except Exception as e:
            self.logger.error(f"❌ Error updating trade status: {e}")

    def _is_dry_run(self) -> bool:
        """Check if we're in dry run mode."""
        if self.settings:
            return getattr(self.settings, 'DRY_RUN', True)
        return True

    def _log_final_stats(self):
        """Log final statistics when stopping."""
        if self.stats['started_at']:
            runtime = datetime.now() - self.stats['started_at']

            self.logger.info("📊 AutoSellMonitor Final Statistics:")
            self.logger.info(f"   ⏱️  Runtime: {runtime}")
            self.logger.info(f"   🔄 Monitoring cycles: {self.stats['monitoring_cycles']}")
            self.logger.info(f"   📈 Prices fetched: {self.stats['prices_fetched']}")
            self.logger.info(f"   💰 Sells executed: {self.stats['sells_executed']}")
            self.logger.info(f"   ✅ Trades closed: {self.stats['trades_closed']}")
            self.logger.info(f"   ❌ API errors: {self.stats['api_errors']}")

    async def get_monitoring_status(self) -> Dict[str, Any]:
        """Get current monitoring status and statistics."""
        return {
            'is_running': self.is_running,
            'open_trades_count': len(self.open_trades),
            'pairs_monitored': list(set(trade.pair for trade in self.open_trades.values())),
            'last_price_fetch': self.last_price_fetch.isoformat() if self.last_price_fetch != datetime.min else None,
            'statistics': self.stats.copy(),
            'next_cycle_in_seconds': self.monitor_interval if self.is_running else None
        }

    async def force_check_trade(self, trade_id: int) -> Optional[Dict[str, Any]]:
        """Force check a specific trade immediately (for testing/debugging)."""
        if trade_id not in self.open_trades:
            await self._load_open_trades()

        trade = self.open_trades.get(trade_id)
        if not trade:
            return None

        # Fetch current price for this pair
        try:
            url = f"https://api.mexc.com/api/v3/ticker/price?symbol={trade.pair}"
            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()

            current_price = float(data.get('price', 0))
            if current_price > 0:
                price_data = PriceData(
                    pair=trade.pair,
                    price=current_price,
                    timestamp=datetime.now()
                )
                self.price_cache[trade.pair] = price_data

                # Analyze and potentially execute
                sell_executed = await self._analyze_and_execute_sell(trade)

                return {
                    'trade_id': trade_id,
                    'current_price': current_price,
                    'buy_price': trade.buy_price,
                    'profit_percentage': ((current_price - trade.buy_price) / trade.buy_price) * 100,
                    'sell_executed': sell_executed
                }

        except Exception as e:
            self.logger.error(f"❌ Error force checking trade {trade_id}: {e}")
            return None


# Example usage (for future integration):
"""
# This is how the AutoSellMonitor would be integrated into the trading system:

async def example_integration():
    from src.auto_sell_monitor import AutoSellMonitor
    from src.database import TradingDatabase
    from src.dry_run.trader import DryRunTrader
    from config.settings import settings

    # Initialize components
    db = TradingDatabase()
    trader = DryRunTrader()

    # Create and start the monitor
    monitor = AutoSellMonitor(db, trader, settings)

    try:
        # Start monitoring (runs indefinitely)
        await monitor.start_monitoring()
    except KeyboardInterrupt:
        print("Stopping monitor...")
        await monitor.stop_monitoring()

# Integration into main.py would look like:
class TradingApp:
    def __init__(self):
        # ... existing initialization ...
        self.auto_sell_monitor = AutoSellMonitor(self.db, self.trader, self.settings, self.logger)

    async def run(self):
        # ... existing startup code ...

        # Start auto-sell monitoring in background
        monitor_task = asyncio.create_task(self.auto_sell_monitor.start_monitoring())

        try:
            # Run main telegram monitoring
            await self.telegram.start(self.on_message)
        finally:
            # Stop auto-sell monitor
            await self.auto_sell_monitor.stop_monitoring()
            monitor_task.cancel()
"""