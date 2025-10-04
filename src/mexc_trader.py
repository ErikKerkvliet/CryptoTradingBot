"""Handles live trading operations for the MEXC exchange."""
import asyncio
import hmac
import hashlib
import time
from typing import Dict, Any, Optional
from urllib.parse import urlencode

import httpx

from .database import TradingDatabase
from config.settings import settings
from .utils.exceptions import InsufficientBalanceError
from src.utils.place_order import PlaceOrder


class MexcTrader:
    """Handles live trading operations on MEXC."""

    BASE_URL = "https://api.mexc.com"
    exchange = "MEXC" # For logging purposes

    def __init__(self, api_key: str, api_secret: str, db: TradingDatabase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = db
        self.enable_trades = getattr(settings, 'ENABLE_TRADES', False)
        self.order_manager = PlaceOrder(db)
        self._client = httpx.AsyncClient(timeout=15)

    async def place_order(self, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Public method to place an order, delegating to the centralized PlaceOrder manager.
        """
        return await self.order_manager.execute(trader=self, **kwargs)

    async def _execute_order(
        self,
        pair: str,
        side: str,
        volume: float,
        ordertype: str,
        price: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Places a spot order on MEXC. Internal method called by PlaceOrder manager."""
        base_currency, quote_currency = self._split_pair(pair)
        params = {
            "symbol": pair.replace("/", ""),
            "side": side.upper(),
            "type": ordertype.upper(),
            "quantity": f"{volume:.8f}",
        }

        if ordertype.lower() == "limit":
            params["price"] = f"{price:.8f}"

        if self.enable_trades:
            res = await self._signed_request("POST", "/api/v3/order", params=params)
        else:
            res = {"orderId": f"simulated_{int(time.time())}"}

        # The actual fill price is not returned immediately for market orders.
        # We use the requested price for limit orders or fetch market price for market orders.
        final_price = price
        if ordertype.lower() == 'market':
            final_price = await self.get_market_price(pair)

        return {
            "status": "open",
            "order_id": res.get("orderId"),
            "price": final_price,
            "base_currency": base_currency,
            "quote_currency": quote_currency
        }

    async def _get_server_time(self) -> int:
        """Fetches the current server time from MEXC."""
        response = await self._client.get(f"{self.BASE_URL}/api/v3/time")
        response.raise_for_status()
        return response.json()["serverTime"]

    def _sign(self, params: Dict[str, Any]) -> str:
        """Signs the request parameters."""
        to_sign = urlencode(params)
        return hmac.new(
            self.api_secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    async def _signed_request(
        self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Makes a signed request to the MEXC API."""
        if params is None:
            params = {}

        timestamp = await self._get_server_time()
        full_params = {**params, "timestamp": timestamp}
        full_params["signature"] = self._sign(full_params)

        headers = {"X-MEXC-APIKEY": self.api_key}
        url = f"{self.BASE_URL}{endpoint}"

        response = await self._client.request(
            method, url, params=full_params, headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def get_balance(self) -> Dict[str, float]:
        """Fetches the account balance from MEXC."""
        try:
            res = await self._signed_request("GET", "/api/v3/account")
            balances = {
                item["asset"]: float(item["free"]) for item in res.get("balances", [])
            }
            return balances
        except Exception as e:
            print(f"Error fetching MEXC balance: {e}")
            return {}

    async def get_market_price(self, pair: str) -> float:
        """Gets the current market price for a pair from MEXC."""
        try:
            url = f"{self.BASE_URL}/api/v3/ticker/price"
            params = {"symbol": pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return float(data["price"])
        except Exception as e:
            print(f"Error fetching MEXC market price for {pair}: {e}")
            return 1.0  # Fallback price

    def _split_pair(self, pair: str) -> tuple[str, str]:
        """Splits a trading pair string into base and quote currencies."""
        # Common quote currencies
        quote_currencies = ["USDT", "USDC", "BTC", "ETH", "EUR", "USD"]
        pair_upper = pair.upper().replace("/", "")

        for quote in quote_currencies:
            if pair_upper.endswith(quote):
                base = pair_upper[:-len(quote)]
                return base, quote

        # Default fallback if no common quote is found
        return pair_upper[:-3], pair_upper[-3:]

    async def close(self):
        """Closes the HTTP client session."""
        await self._client.aclose()