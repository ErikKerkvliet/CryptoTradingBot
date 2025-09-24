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


class MexcTrader:
    """Handles live trading operations on MEXC."""

    BASE_URL = "https://api.mexc.com"

    def __init__(self, api_key: str, api_secret: str, db: TradingDatabase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = db
        self.enable_trades = getattr(settings, 'ENABLE_TRADES', False)
        self._client = httpx.AsyncClient(timeout=15)

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

    async def place_order(
        self,
        pair: str,
        side: str,
        volume: float,
        ordertype: str,
        price: Optional[float] = None,
        telegram_channel: Optional[str] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Places an order on MEXC."""
        base_currency, quote_currency = self._split_pair(pair)
        params = {
            "symbol": pair.replace("/", ""),
            "side": side.upper(),
            "type": ordertype.upper(),
            "quantity": f"{volume:.8f}",  # Format volume to a string with precision
        }

        if ordertype.lower() == "limit":
            if price is None:
                raise ValueError("Price must be specified for limit orders.")
            params["price"] = f"{price:.8f}"

        if self.enable_trades:
            res = await self._signed_request("POST", "/api/v3/order", params=params)
        else:
            # Simulate order placement
            res = {"orderId": f"simulated_{int(time.time())}"}

        trade_data = {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "side": side,
            "volume": volume,
            "price": price,
            "ordertype": ordertype,
            "telegram_channel": telegram_channel,
            "status": "open",  # Assuming it's open, MEXC response might differ
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            **kwargs,
        }

        self.db.add_trade(trade_data)
        return {"status": "success", "order_id": res.get("orderId"), **trade_data}

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