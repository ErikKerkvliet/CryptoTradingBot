"""Handles live futures trading operations for the MEXC exchange."""
import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional

import httpx

from ..database import TradingDatabase
from config.settings import settings
from src.utils.exceptions import InsufficientBalanceError
from src.utils.place_order import PlaceOrder


class MexcFuturesTrader:
    """Handles live futures trading operations on MEXC Futures."""

    BASE_URL = "https://contract.mexc.com"
    exchange = "MEXC_FUTURES" # For logging

    def __init__(self, api_key: str, api_secret: str, db: TradingDatabase, default_leverage: int):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = db
        self.default_leverage = default_leverage
        self.enable_trades = getattr(settings, 'ENABLE_TRADES', False)
        self.order_manager = PlaceOrder(db)
        self._client = httpx.AsyncClient(timeout=20)

    async def place_order(self, **kwargs) -> Optional[Dict[str, Any]]:
        """
        Public method to place a futures order, delegating to the centralized PlaceOrder manager.
        """
        return await self.order_manager.execute(trader=self, **kwargs)

    async def _execute_order(
            self,
            pair: str,
            side: str,
            volume: float,
            ordertype: str,
            price: Optional[float] = None,
            leverage: int = 0,
            **kwargs,
    ) -> Dict[str, Any]:
        """Places a futures order on MEXC. Internal method called by PlaceOrder manager."""
        # 1: Open long, 2: Close short, 3: Open short, 4: Close long
        # This logic assumes we are always opening positions with this call.
        # A more complex system would handle closing existing positions.
        trade_side = 1 if side.lower() == "buy" else 3

        final_leverage = leverage or self.default_leverage
        await self.set_leverage(pair, final_leverage)

        params = {
            "symbol": pair,
            "price": float(price) if ordertype.lower() == "limit" else None,
            "vol": float(volume),
            "leverage": final_leverage,
            "side": trade_side,
            "type": 1 if ordertype.lower() == "limit" else 6,  # 1 for limit, 6 for market
            "openType": 1,  # 1 for cross, 2 for isolated
        }
        # Remove price from params if it's a market order
        if params["price"] is None:
            del params["price"]

        if self.enable_trades:
            order_data = await self._signed_request("POST", "/api/v1/private/order/place", params)
            order_id = order_data # The whole response is the order ID data
        else:
            order_id = f"simulated_{int(time.time())}"

        final_price = price
        if ordertype.lower() == 'market':
            final_price = await self.get_market_price(pair)

        return {
            "status": "open",
            "order_id": order_id,
            "price": final_price,
            "base_currency": pair.replace("_USDT", ""),
            "quote_currency": "USDT"
        }

    def _sign(self, timestamp: str, params_str: str = "") -> str:
        """Signs the request parameters for MEXC Futures API."""
        to_sign = timestamp + self.api_key + params_str
        return hmac.new(
            self.api_secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    async def _signed_request(
            self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Makes a signed request to the MEXC Futures API."""
        if params is None:
            params = {}

        # Fetch server time for timestamp
        ping_response = await self._client.get("https://contract.mexc.com/api/v1/contract/ping")
        ping_response.raise_for_status()
        timestamp = str(ping_response.json()['data'])


        param_str = ""
        if method.upper() == "GET":
            # Filter out None values before creating the query string
            filtered_params = {k: v for k, v in params.items() if v is not None}
            param_str = "&".join([f"{k}={v}" for k, v in sorted(filtered_params.items())])
        else:  # POST
            # Filter out None values from the dictionary before dumping to JSON
            filtered_params = {k: v for k, v in params.items() if v is not None}
            param_str = json.dumps(filtered_params)


        headers = {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Signature": self._sign(timestamp, param_str),
            "Content-Type": "application/json",
        }

        url = f"{self.BASE_URL}{endpoint}"

        if method.upper() == "GET":
            response = await self._client.get(url, params=params, headers=headers)
        else:  # POST
            response = await self._client.post(url, json=params, headers=headers)

        response.raise_for_status()
        res_json = response.json()

        if not res_json.get("success"):
            raise Exception(f"MEXC Futures API Error: {res_json.get('message')} (Code: {res_json.get('code')})")

        return res_json.get("data", {})

    async def get_balance(self) -> Dict[str, float]:
        """Fetches the futures account balance from MEXC (typically in USDT)."""
        try:
            res = await self._signed_request("GET", "/api/v1/private/account/assets")
            balances = {item["currency"]: float(item["availableBalance"]) for item in res}
            return balances
        except Exception as e:
            print(f"Error fetching MEXC Futures balance: {e}")
            return {}

    async def get_market_price(self, pair: str) -> float:
        """Gets the current market price for a futures contract from MEXC."""
        try:
            url = f"{self.BASE_URL}/api/v1/contract/ticker"
            params = {"symbol": pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return float(data["data"]["lastPrice"])
        except Exception as e:
            print(f"Error fetching MEXC Futures market price for {pair}: {e}")
            return 1.0

    async def set_leverage(self, pair: str, leverage: int):
        """Sets the leverage for a specific symbol."""
        try:
            # Position ID 0 for all, openType 1 for cross margin.
            params = {"symbol": pair, "leverage": leverage, "openType": 1}
            await self._signed_request("POST", "/api/v1/private/position/change_leverage", params)
            self.db.logger.info(f"Set leverage for {pair} to {leverage}x")
        except Exception as e:
            # Catch exceptions where leverage is already set to the desired value
            if 'leverage not modified' in str(e).lower():
                self.db.logger.info(f"Leverage for {pair} is already set to {leverage}x.")
            else:
                self.db.logger.error(f"Failed to set leverage for {pair}: {e}")
                raise

    async def close(self):
        """Closes the HTTP client session."""
        await self._client.aclose()