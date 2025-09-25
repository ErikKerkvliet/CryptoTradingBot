"""Handles live trading operations for the Kraken exchange."""
import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Dict, Any, Optional

import httpx

from .database import TradingDatabase
from .utils.exceptions import InsufficientBalanceError

from config.settings import settings

class KrakenTrader:
    """Handles live trading operations on Kraken."""

    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str, db: TradingDatabase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = db
        self.enable_trades = getattr(settings, 'ENABLE_TRADES', False)
        self._client = httpx.AsyncClient(timeout=15)

    async def _get_kraken_signature(self, url_path: str, data: Dict[str, Any]) -> str:
        """Signs the request."""
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + postdata).encode()
        message = url_path.encode() + hashlib.sha256(encoded).digest()

        mac = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return sigdigest.decode()

    async def _signed_request(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Makes a signed request to the Kraken API."""
        if params is None:
            params = {}

        params["nonce"] = int(time.time() * 1000)
        headers = {
            "API-Key": self.api_key,
            "API-Sign": await self._get_kraken_signature(endpoint, params),
        }
        url = f"{self.BASE_URL}{endpoint}"

        response = await self._client.post(url, data=params, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("error"):
            raise Exception(f"Kraken API error: {result['error']}")
        return result.get("result", {})

    async def get_balance(self) -> Dict[str, float]:
        """Fetches the account balance from Kraken."""
        try:
            res = await self._signed_request("/0/private/Balance")
            # Kraken prefixes some assets with Z or X, so we remove them for consistency
            return {
                key.replace("X", "").replace("Z", ""): float(value)
                for key, value in res.items()
            }
        except Exception as e:
            print(f"Error fetching Kraken balance: {e}")
            return {}

    async def get_market_price(self, pair: str) -> float:
        """Gets the current market price for a pair from Kraken."""
        try:
            url = f"{self.BASE_URL}/0/public/Ticker"
            params = {"pair": pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("result"):
                # The pair name is the key in the result dictionary
                pair_key = list(data["result"].keys())[0]
                return float(data["result"][pair_key]["c"][0])
            raise ValueError("Invalid response from Kraken API for market price")
        except Exception as e:
            print(f"Error fetching Kraken market price for {pair}: {e}")
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
        targets: Optional[list] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Places an order on Kraken."""
        base_currency, quote_currency = pair.split("/")
        params = {
            "pair": pair,
            "type": side.lower(),
            "ordertype": ordertype.lower(),
            "volume": f"{volume:.8f}",
        }

        if ordertype.lower() == "limit" and price:
            params["price"] = f"{price:.8f}"

        if take_profit:
            params["price2"] = f"{take_profit:.8f}" # Price2 is used for take profit orders

        if stop_loss:
            params["stop-loss-price"] = f"{stop_loss:.8f}"

        if self.enable_trades:
            res = await self._signed_request("/0/private/AddOrder", params)
        else:
            # Simulate order placement
            res = {"txid": [f"simulated_{int(time.time())}"]}

        trade_data = {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "side": side,
            "volume": volume,
            "price": price,
            "ordertype": ordertype,
            "telegram_channel": telegram_channel,
            "status": "open",
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "targets": targets if side.lower() == 'buy' else None,
            **kwargs,
        }
        self.db.add_trade(trade_data)

        return {"status": "success", "txid": res.get("txid"), **trade_data}

    async def close(self):
        """Closes the HTTP client session."""
        await self._client.aclose()