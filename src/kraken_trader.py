"""KrakenTrader handles connectivity and order execution on Kraken."""
from __future__ import annotations
from typing import Dict, Any, Optional
import time
import hmac
import hashlib
import base64
import urllib.parse
import httpx
import asyncio
from .utils.exceptions import InsufficientBalanceError


class KrakenTrader:
    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str, dry_run: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.dry_run = dry_run
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
        return r.json()

    async def get_balance(self) -> Dict[str, float]:
        resp = await self._private("Balance")
        return {k: float(v) for k, v in resp.get("result", {}).items()}

    async def place_order(self, pair: str, side: str, volume: float, ordertype: str = "market", price: Optional[float] = None) -> Dict[str, Any]:
        """Place an order. pair must be Kraken's asset name like XBTUSDC or
        ETHUSDC (altname)."""
        if self.dry_run:
            return {"status": "dry_run", "pair": pair, "side": side, "volume":
                volume, "ordertype": ordertype, "price": price}
        data = {
            "pair": pair,
            "type": side.lower(),
            "ordertype": ordertype,
            "volume": str(volume),
        }
        if price is not None and ordertype.lower() == "limit":
            data["price"] = str(price)
        resp = await self._private("AddOrder", data)
        return resp

    async def close(self):
        await self._client.aclose()