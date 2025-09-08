"""KrakenTrader handles connectivity and order execution on Kraken."""
from __future__ import annotations
from typing import Dict, Any, Optional
import time
import hmac
import hashlib
import base64
import urllib.parse
import httpx
import re
from .database import TradingDatabase
from .utils.exceptions import InsufficientBalanceError


class KrakenTrader:
    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str, db: TradingDatabase):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = db
        self._client = httpx.AsyncClient(timeout=15)

    async def _public(self, path: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        r = await self._client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    async def _private(self, path: str, data: Dict[str, Any] = None) -> Dict[str, Any]:

        if data is None:
            data = {}
        url_path = f"/0/private/{path}"
        nonce = str(int(1000 * time.time()))
        data["nonce"] = nonce
        postdata = urllib.parse.urlencode(data)
        message = (nonce + postdata).encode()
        sha256 = hashlib.sha256(message).digest()
        mac = hmac.new(base64.b64decode(self.api_secret), (url_path.encode() +
                                                           sha256), hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        headers = {
            "API-Key": self.api_key,
            "API-Sign": sigdigest.decode(),
        }
        url = f"{self.BASE_URL}{url_path}"
        r = await self._client.post(url, data=data, headers=headers)
        r.raise_for_status()
        response_data = r.json()
        if response_data.get("error"):
            raise Exception(f"Kraken API error: {response_data['error']}")
        return response_data

    async def get_balance(self) -> Dict[str, float]:
        resp = await self._private("Balance")
        # Kraken prefixes assets with 'Z' or 'X' sometimes, let's normalize them
        normalized_balances = {}
        for k, v in resp.get("result", {}).items():
            # Remove the Z/X prefix and '.S' for staked assets for consistency
            key = re.sub(r'^[ZX]([A-Z0-9]+)(\.S)?$', r'\1', k)
            normalized_balances[key] = float(v)
        return normalized_balances

    async def place_order(self, pair: str, side: str, volume: float, ordertype: str = "market", price: Optional[float] = None, telegram_channel: Optional[str] = None) -> Dict[str, Any]:
        """Place an order and record it in the database."""
        kraken_pair = pair.replace("/", "")
        base_currency, quote_currency = pair.split('/')

        data = {
            "pair": kraken_pair,
            "type": side.lower(),
            "ordertype": ordertype,
            "volume": str(volume),
        }
        if price is not None and ordertype.lower() == "limit":
            data["price"] = str(price)

        resp = await self._private("AddOrder", data)

        # Record the trade in the live database
        trade_data = {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "side": side,
            "volume": volume,
            "price": price,
            "ordertype": ordertype,
            "telegram_channel": telegram_channel,
            "status": "submitted"  # Or parse from response
        }
        self.db.add_trade(trade_data)
        return resp

    async def close(self):
        await self._client.aclose()