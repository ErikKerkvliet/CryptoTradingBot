"""Handles live futures trading operations for the MEXC exchange."""
import hmac
import hashlib
import json
import time
from typing import Dict, Any, Optional

import httpx

from ..database import TradingDatabase
from config.settings import settings
from ..utils.exceptions import InsufficientBalanceError


class MexcFuturesTrader:
    """Handles live futures trading operations on MEXC Futures."""

    BASE_URL = "https://contract.mexc.com"

    def __init__(self, api_key: str, api_secret: str, db: TradingDatabase, default_leverage: int):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = db
        self.default_leverage = default_leverage
        self.enable_trades = getattr(settings, 'ENABLE_TRADES', False)
        self._client = httpx.AsyncClient(timeout=20)

    def _sign(self, timestamp: str, params: str = "") -> str:
        """Signs the request parameters for MEXC Futures API."""
        to_sign = timestamp + self.api_key + params
        return hmac.new(
            self.api_secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    async def _signed_request(
            self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Makes a signed request to the MEXC Futures API."""
        if params is None:
            params = {}

        timestamp = str(int(httpx.get("https://contract.mexc.com/api/v1/contract/ping").json()['data']['timestamp']))

        param_str = ""
        if method.upper() == "GET":
            param_str = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        else:  # POST
            param_str = json.dumps(params)

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
            # Position ID 1 for long, 2 for short. Leverage is same for both.
            params = {"symbol": pair, "leverage": leverage, "openType": 1, "positionId": 0}
            await self._signed_request("POST", "/api/v1/private/position/change_leverage", params)
            self.db.logger.info(f"Set leverage for {pair} to {leverage}x")
        except Exception as e:
            self.db.logger.error(f"Failed to set leverage for {pair}: {e}")
            raise

    async def place_order(
            self,
            pair: str,
            side: str,
            volume: float,
            ordertype: str,
            price: Optional[float] = None,
            leverage: int = 0,
            targets: Optional[list] = None,
            **kwargs,
    ) -> Dict[str, Any]:
        """Places a futures order on MEXC."""

        # 1: Open long, 2: Close short, 3: Open short, 4: Close long
        open_type = 1 if side.lower() == "buy" else 2

        # Ensure leverage is set
        final_leverage = leverage or self.default_leverage
        await self.set_leverage(pair, final_leverage)

        params = {
            "symbol": pair,
            "price": float(price) if ordertype.lower() == "limit" else 0,
            "vol": float(volume),
            "leverage": final_leverage,
            "side": 1 if side.lower() == "buy" else 3,  # 1 for open long, 3 for open short
            "type": 1 if ordertype.lower() == "limit" else 6,  # 1 for limit, 6 for market
            "openType": 1,  # 1 for cross, 2 for isolated
        }

        if self.enable_trades:
            order_id = await self._signed_request("POST", "/api/v1/private/order/place", params)
        else:
            # Simulate order placement
            order_id = {"orderId": f"simulated_{int(time.time())}"}

        trade_data = {
            "base_currency": pair.replace("_USDT", ""),
            "quote_currency": "USDT",
            "side": side,
            "volume": volume,
            "price": price,
            "ordertype": ordertype,
            "status": "open",
            "leverage": final_leverage,
            "targets": targets if side.lower() == 'buy' else None,
            **kwargs,
        }

        self.db.add_trade(trade_data)
        return {"status": "success", "order_id": order_id, **trade_data}

    async def close(self):
        """Closes the HTTP client session."""
        await self._client.aclose()