"""Enhanced dry run trader with channel-specific balance management."""
from typing import Dict, Any, Optional
import httpx
from ..utils.exceptions import InsufficientBalanceError
from .database import DryRunDatabase
from .wallet import VirtualWallet


class DryRunTrader:
    """
    Enhanced simulated trader that manages channel-specific wallets.
    Each channel has its own isolated balance and can only trade with its own funds.
    """

    def __init__(self, exchange: str = "KRAKEN", trading_mode: str = "SPOT",
                 api_key: str = None, api_secret: str = None,
                 channel_configs: Dict[str, Dict[str, float]] = None):
        self.exchange = exchange.upper()
        self.trading_mode = trading_mode.upper()
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = DryRunDatabase()

        # Initialize wallet with channel configurations
        self.wallet = VirtualWallet(self.db, channel_configs=channel_configs)
        self.wallet.reset()

        self._client = httpx.AsyncClient(timeout=15)

    async def get_balance(self, channel: str = None) -> Dict[str, float]:
        """
        Get balance for a specific channel or global balance.
        If channel is provided, returns that channel's isolated balance.
        """
        if channel:
            return self.wallet.get_channel_balance(channel)
        else:
            # Return global balance for backwards compatibility
            return self.wallet.get_balance()

    async def get_market_price(self, pair: str) -> float:
        """Get the current market price from the configured exchange and mode."""
        if self.trading_mode == "FUTURES":
            # Currently, only MEXC is supported for futures dry-run prices
            return await self._get_mexc_futures_market_price(pair)

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
            url = "https://api.kraken.com/0/public/Ticker"
            params = {"pair": pair.replace("/", "")}
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
            url = "https://api.mexc.com/api/v3/ticker/price"
            params = {"symbol": pair.replace("/", "")}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
        except Exception as e:
            print(f"Error fetching MEXC market price for {pair}: {e}")
            return 1.0

    async def _get_mexc_futures_market_price(self, pair: str) -> float:
        """Get the current market price for a futures contract from MEXC."""
        try:
            url = "https://contract.mexc.com/api/v1/contract/ticker"
            params = {"symbol": pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("success"):
                return float(data["data"]["lastPrice"])
            raise ValueError(f"Invalid response from MEXC Futures API: {data.get('message')}")
        except Exception as e:
            print(f"Error fetching MEXC Futures market price for {pair}: {e}")
            return 1.0

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

    async def place_order(self, pair: str, side: str, volume: float, ordertype: str = "market",
                          price: Optional[float] = None, telegram_channel: Optional[str] = None,
                          take_profit: Optional[float] = None, stop_loss: Optional[float] = None,
                          take_profit_target: Optional[int] = None, leverage: int = 0) -> Dict[str, Any]:
        """
        Simulate placing an order with channel-specific balance management.
        Each channel can only use its own isolated funds.
        """
        # Auto-initialize channel wallet if it doesn't exist
        if telegram_channel:
            self.wallet.initialize_channel_if_needed(telegram_channel)

        # Get the appropriate balance (channel-specific or global)
        if telegram_channel:
            balances = self.wallet.get_channel_balance(telegram_channel)
            balance_source = f"channel '{telegram_channel}'"
        else:
            balances = self.wallet.get_balance()
            balance_source = "global wallet"

        base_currency, quote_currency = self._split_pair(pair)

        if ordertype == "market" and price is None:
            price = await self.get_market_price(pair)

        cost = volume * (price or 0)

        if self.trading_mode == "FUTURES":
            # In futures, the cost is the margin, which is affected by leverage
            leverage_used = leverage if leverage > 0 else 1
            cost /= leverage_used

        print(f"💰 Using {balance_source} - Available balances: {balances}")

        if side.lower() == "buy":
            available_quote = balances.get(quote_currency, 0)
            if available_quote < cost:
                raise InsufficientBalanceError(
                    f"Insufficient {quote_currency} in {balance_source} for the trade. "
                    f"Need {cost:.2f}, have {available_quote:.2f}"
                )

            # Update balances
            new_quote_balance = available_quote - cost
            new_base_balance = balances.get(base_currency, 0) + volume

            if telegram_channel:
                self.wallet.update_channel_balance(telegram_channel, quote_currency, new_quote_balance)
                self.wallet.update_channel_balance(telegram_channel, base_currency, new_base_balance)
            else:
                self.wallet.update_balance(quote_currency, new_quote_balance)
                self.wallet.update_balance(base_currency, new_base_balance)

            print(f"✅ BUY executed: {volume:.8f} {base_currency} for {cost:.2f} {quote_currency}")
            print(f"   New {quote_currency} balance: {new_quote_balance:.2f}")
            print(f"   New {base_currency} balance: {new_base_balance:.8f}")

        else:  # Sell
            available_base = balances.get(base_currency, 0)
            if available_base < volume:
                raise InsufficientBalanceError(
                    f"Insufficient {base_currency} in {balance_source} to sell. "
                    f"Need {volume}, have {available_base}"
                )

            # Update balances
            new_base_balance = available_base - volume
            new_quote_balance = balances.get(quote_currency, 0) + cost

            if telegram_channel:
                self.wallet.update_channel_balance(telegram_channel, base_currency, new_base_balance)
                self.wallet.update_channel_balance(telegram_channel, quote_currency, new_quote_balance)
            else:
                self.wallet.update_balance(base_currency, new_base_balance)
                self.wallet.update_balance(quote_currency, new_quote_balance)

            print(f"✅ SELL executed: {volume:.8f} {base_currency} for {cost:.2f} {quote_currency}")
            print(f"   New {base_currency} balance: {new_base_balance:.8f}")
            print(f"   New {quote_currency} balance: {new_quote_balance:.2f}")

        # Record the trade in database
        trade_data = {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "side": side,
            "volume": volume,
            "price": price,
            "ordertype": ordertype,
            "telegram_channel": telegram_channel,
            "status": "simulated_open",
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "take_profit_target": take_profit_target,
            "leverage": leverage if self.trading_mode == "FUTURES" else 0,
        }
        self.db.add_trade(trade_data)

        return {"status": "simulated_open", **trade_data}

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
        self.db.close()
        await self._client.aclose()