"""Enhanced dry run trader with improved spot and futures support for auto-sell monitor."""
from typing import Dict, Any, Optional
import httpx
from src.utils.exceptions import InsufficientBalanceError
from src.database import TradingDatabase
from .wallet import VirtualWallet
from src.utils.place_order import PlaceOrder


class DryRunTrader:
    """
    Enhanced simulated trader that manages channel-specific wallets with improved
    spot and futures support for the auto-sell monitor.
    """

    def __init__(self, exchange: str, trading_mode: str, db: TradingDatabase,
                 channel_configs: Dict[str, Dict[str, float]] = None):
        self.exchange = exchange.upper()
        self.trading_mode = trading_mode.upper()
        self.db = db
        self.order_manager = PlaceOrder(db)

        # Initialize wallet with channel configurations
        self.wallet = VirtualWallet(self.db, channel_configs=channel_configs)
        self.wallet.reset()

        self._client = httpx.AsyncClient(timeout=15)

    async def place_order(self, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Public method to place an order, which delegates to the centralized PlaceOrder manager.
        """
        return await self.order_manager.execute(trader=self, **kwargs)

    async def _execute_order(self, pair: str, side: str, volume: float, ordertype: str,
                           price: Optional[float] = None, telegram_channel: Optional[str] = None,
                           leverage: int = 0) -> Dict[str, Any]:
        """
        Simulate placing an order. This is the internal method called by the PlaceOrder manager.
        """
        # Auto-initialize channel wallet if it doesn't exist
        if telegram_channel:
            self.wallet.initialize_channel_if_needed(telegram_channel)

        normalized_pair = self._normalize_pair_format(pair)

        if telegram_channel:
            balances = self.wallet.get_channel_balance(telegram_channel)
            balance_source = f"channel '{telegram_channel}'"
        else:
            balances = self.wallet.get_balance()
            balance_source = "global wallet"

        base_currency, quote_currency = self._split_pair(normalized_pair)

        if ordertype == "market" and price is None:
            price = await self.get_market_price(normalized_pair)

        cost = volume * (price or 0)

        if self.trading_mode == "FUTURES":
            leverage_used = leverage if leverage > 0 else 1
            cost /= leverage_used
            print(f"💰 Futures trade with {leverage_used}x leverage - Margin required: {cost:.2f} {quote_currency}")

        print(f"💰 Using {balance_source} - Available balances: {balances}")

        if side.lower() == "buy":
            available_quote = balances.get(quote_currency, 0)
            if available_quote < cost:
                raise InsufficientBalanceError(
                    f"Insufficient {quote_currency} in {balance_source} for the trade. "
                    f"Need {cost:.2f}, have {available_quote:.2f}"
                )
            new_quote_balance = available_quote - cost
            new_base_balance = balances.get(base_currency, 0) + volume
        else:  # sell
            available_base = balances.get(base_currency, 0)
            if available_base < volume:
                raise InsufficientBalanceError(
                    f"Insufficient {base_currency} in {balance_source} for the trade. "
                    f"Need {volume:.8f}, have {available_base:.8f}"
                )
            new_base_balance = available_base - volume
            new_quote_balance = balances.get(quote_currency, 0) + cost

        if telegram_channel:
            self.wallet.update_channel_balance(telegram_channel, quote_currency, new_quote_balance)
            self.wallet.update_channel_balance(telegram_channel, base_currency, new_base_balance)
        else:
            self.wallet.update_balance(quote_currency, new_quote_balance)
            self.wallet.update_balance(base_currency, new_base_balance)

        await self._record_wallet_snapshot(telegram_channel)

        return {
            "status": "simulated_open",
            "price": price,
            "base_currency": base_currency,
            "quote_currency": quote_currency
        }

    async def get_balance(self, channel: str = None, currency: str = None) -> Dict[str, float]:
        """
        Get balance for a specific channel or global balance.
        If channel is provided, returns that channel's isolated balance.
        """
        if channel:
            return self.wallet.get_channel_balance(channel, currency)
        else:
            # Return global balance for backwards compatibility
            return self.wallet.get_balance()

    async def get_market_price(self, pair: str) -> float:
        """Get the current market price from the configured exchange and mode."""
        if self.trading_mode == "FUTURES":
            # For futures, determine the correct API endpoint and format
            if self.exchange == "MEXC":
                return await self._get_mexc_futures_market_price(pair)
            else:
                print(f"Unsupported exchange for futures market data: {self.exchange}")
                return 1.0

        # Spot mode
        if self.exchange == "KRAKEN":
            return await self._get_kraken_market_price(pair)
        elif self.exchange == "MEXC":
            return await self._get_mexc_market_price(pair)
        else:
            print(f"Unsupported exchange for spot market data: {self.exchange}")
            return 1.0

    async def _get_kraken_market_price(self, pair: str) -> float:
        """Get the current market price from Kraken Spot."""
        try:
            # Handle different pair formats
            kraken_pair = pair.replace("/", "").replace("_", "")
            url = "https://api.kraken.com/0/public/Ticker"
            params = {"pair": kraken_pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("result"):
                result_key = list(data["result"].keys())[0]
                return float(data["result"][result_key]["c"][0])
            raise ValueError("Invalid response from Kraken API")
        except Exception as e:
            print(f"Error fetching Kraken market price for {pair}: {e}")
            return 1.0

    async def _get_mexc_market_price(self, pair: str) -> float:
        """Get the current market price from MEXC Spot."""
        try:
            # Convert pair format for MEXC spot (BTC/USDT -> BTCUSDT)
            mexc_pair = pair.replace("/", "").replace("_", "")
            url = "https://api.mexc.com/api/v3/ticker/price"
            params = {"symbol": mexc_pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
        except Exception as e:
            print(f"Error fetching MEXC spot market price for {pair}: {e}")
            return 1.0

    async def _get_mexc_futures_market_price(self, pair: str) -> float:
        """Get the current market price for a futures contract from MEXC."""
        try:
            # Convert pair format for MEXC futures (BTC/USDT -> BTC_USDT)
            mexc_futures_pair = pair.replace("/", "_")
            if "_" not in mexc_futures_pair and "/" not in pair:
                # Handle BTCUSDT -> BTC_USDT conversion
                mexc_futures_pair = self._convert_spot_to_futures_pair(pair)

            url = "https://contract.mexc.com/api/v1/contract/ticker"
            params = {"symbol": mexc_futures_pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                return float(data["data"]["lastPrice"])
            raise ValueError(f"Invalid response from MEXC Futures API: {data.get('message')}")
        except Exception as e:
            print(f"Error fetching MEXC Futures market price for {pair}: {e}")
            return 1.0

    def _convert_spot_to_futures_pair(self, spot_pair: str) -> str:
        """Convert spot pair format to futures pair format."""
        # Common quote currencies for futures
        quote_currencies = ["USDT", "USDC", "BTC", "ETH"]

        for quote in quote_currencies:
            if spot_pair.endswith(quote):
                base = spot_pair[:-len(quote)]
                return f"{base}_{quote}"

        # Default assumption - pair ends with USDT
        if len(spot_pair) > 4:
            return f"{spot_pair[:-4]}_USDT"

        return spot_pair

    def _split_pair(self, pair: str) -> tuple[str, str]:
        """Splits a trading pair string into base and quote currencies."""
        if "/" in pair:  # Kraken spot format e.g. XBT/USDC
            return pair.split('/')
        if "_" in pair: # MEXC futures format e.g. BTC_USDT
            return pair.split('_')

        # MEXC spot format e.g. BTCUSDT
        quote_currencies = ["USDT", "USDC", "BTC", "ETH", "EUR", "USD"]
        pair_upper = pair.upper()

        for quote in quote_currencies:
            if pair_upper.endswith(quote):
                base = pair_upper[:-len(quote)]
                return base, quote

        # Default fallback
        return pair_upper[:-4] if pair_upper.endswith("USDT") else pair_upper[:-3], "USDT"

    def _normalize_pair_format(self, pair: str) -> str:
        """Normalize pair format for internal storage and API calls."""
        if self.trading_mode == "FUTURES":
            # Futures pairs should use underscore format (BTC_USDT)
            if "/" in pair:
                return pair.replace("/", "_")
            elif "_" not in pair:
                # Convert BTCUSDT to BTC_USDT
                return self._convert_spot_to_futures_pair(pair)
            return pair
        else:
            # Spot pairs - remove separators for MEXC, keep / for Kraken
            if self.exchange == "MEXC":
                return pair.replace("/", "").replace("_", "")
            else:  # Kraken
                if "_" in pair:
                    return pair.replace("_", "/")
                elif "/" not in pair:
                    # Convert BTCUSDT to BTC/USDT for Kraken
                    base, quote = self._split_pair(pair)
                    return f"{base}/{quote}"
                return pair

    async def _record_wallet_snapshot(self, channel: str):
        """Records the current total USD value and full balance snapshot of a channel's wallet."""
        if not channel:
            return

        try:
            balances = self.wallet.get_channel_balance(channel)
            total_usd_value = 0.0

            for currency, amount in balances.items():
                if amount > 1e-9: # Use a small threshold for floating point precision
                    if currency.upper() in ["USDT", "USDC", "USD"]:
                        total_usd_value += amount
                    else:
                        # Fetch price for non-stablecoins to get USD value
                        # Create appropriate pair format for price fetching
                        if self.trading_mode == "FUTURES":
                            pair_for_price = f"{currency.upper()}_USDT"
                        else:
                            pair_for_price = f"{currency.upper()}USDT"

                        price = await self.get_market_price(pair_for_price)
                        total_usd_value += amount * price

            # Pass the full balances dictionary to the database method
            self.db.add_wallet_history_record(channel, total_usd_value, balances)
            print(f"📈 Recorded wallet snapshot for '{channel}': ${total_usd_value:.2f}")

        except Exception as e:
            print(f"⚠️  Could not record wallet snapshot for '{channel}': {e}")

    def get_channel_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for all channels."""
        summary = {}

        # Get all unique channels
        self.db.cursor.execute("""
            SELECT DISTINCT telegram_channel FROM wallet
            WHERE telegram_channel IS NOT NULL
        """)
        channels = [row[0] for row in self.db.cursor.fetchall()]

        for channel in channels:
            summary[channel] = self.wallet.get_channel_performance(channel)

        return summary

    def get_all_balances(self) -> Dict[str, Dict[str, float]]:
        """Get all balances organized by channel."""
        return self.wallet.get_all_balances()

    async def close(self):
        """Close the database and client connections."""
        try:
            await self._client.aclose()
            if hasattr(self.db, 'close'):
                self.db.close()
        except Exception as e:
            print(f"Warning: Error closing connections: {e}")