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
from src.utils.place_order import PlaceOrder

class KrakenTrader:
    """Handles live trading operations on Kraken."""

    BASE_URL = "https://api.kraken.com"
    exchange = "KRAKEN" # For logging purposes

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
        **kwargs, # Absorb unused kwargs
    ) -> Dict[str, Any]:
        """
        Places an order on Kraken. This is the internal method called by the PlaceOrder manager.
        """
        base_currency, quote_currency = pair.split("/")
        params = {
            "pair": pair,
            "type": side.lower(),
            "ordertype": ordertype.lower(),
            "volume": f"{volume:.8f}",
        }

        if ordertype.lower() == "limit" and price:
            params["price"] = f"{price:.8f}"

        if self.enable_trades:
            res = await self._signed_request("/0/private/AddOrder", params)
        else:
            # Simulate order placement
            res = {"txid": [f"simulated_{int(time.time())}"]}

        # Kraken doesn't return the fill price on order creation, so we use the requested price.
        # A more advanced system would poll the order status to get the actual fill price.
        return {
            "status": "open",
            "order_id": res.get("txid", [None])[0],
            "price": price,
            "base_currency": base_currency,
            "quote_currency": quote_currency
        }

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

    async def close(self):
        """Closes the HTTP client session."""
        await self._client.aclose()