"""Simulates a trader for dry-run mode, fetching live prices from a real exchange."""
from typing import Dict, Any, Optional
import httpx
from ..utils.exceptions import InsufficientBalanceError
from .database import DryRunDatabase
from .wallet import VirtualWallet


class DryRunTrader:
    """
    Simulates trading operations for both SPOT and FUTURES.
    Fetches live market prices from the configured exchange to make the simulation realistic.
    """

    def __init__(self, exchange: str = "KRAKEN", trading_mode: str = "SPOT", api_key: str = None, api_secret: str = None):
        self.exchange = exchange.upper()
        self.trading_mode = trading_mode.upper()
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = DryRunDatabase()
        self.wallet = VirtualWallet(self.db)
        self.wallet.reset()
        self._client = httpx.AsyncClient(timeout=15)

    async def get_balance(self) -> Dict[str, float]:
        """Get the virtual wallet balance."""
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
            # Futures pair format is like BTC_USDT
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
                          take_profit_key: Optional[int] = None, leverage: int = 0) -> Dict[str, Any]:
        """Simulate placing an order and record it in the database."""
        balances = self.wallet.get_balance()
        base_currency, quote_currency = self._split_pair(pair)

        if ordertype == "market" and price is None:
            price = await self.get_market_price(pair)

        cost = volume * (price or 0)

        if self.trading_mode == "FUTURES":
            # In futures, the cost is the margin, which is affected by leverage
            leverage_used = leverage if leverage > 0 else 1
            cost /= leverage_used

        if side.lower() == "buy":
            if balances.get(quote_currency, 0) < cost:
                raise InsufficientBalanceError(f"Insufficient {quote_currency} for the trade. Need {cost:.2f}, have {balances.get(quote_currency, 0):.2f}")
            self.wallet.update_balance(quote_currency, balances[quote_currency] - cost)
            self.wallet.update_balance(base_currency, balances.get(base_currency, 0) + volume)
        else:  # Sell
            if balances.get(base_currency, 0) < volume:
                raise InsufficientBalanceError(f"Insufficient {base_currency} to sell. Need {volume}, have {balances.get(base_currency, 0)}")
            self.wallet.update_balance(base_currency, balances[base_currency] - volume)
            self.wallet.update_balance(quote_currency, balances.get(quote_currency, 0) + cost)

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
            "take_profit_target": take_profit_key,
            "leverage": leverage if self.trading_mode == "FUTURES" else 0,
        }
        self.db.add_trade(trade_data)

        return {"status": "simulated_open", **trade_data}

    async def close(self):
        """Close the database and client connections."""
        self.db.close()
        await self._client.aclose()