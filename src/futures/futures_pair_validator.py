"""Pair validation for futures trading on MEXC."""
import asyncio
from typing import Set, Tuple

import httpx

from ..utils.exceptions import PairNotFoundError


class FuturesPairValidator:
    """Validates futures contract pairs against the MEXC API."""

    MEXC_FUTURES_CONTRACTS_URL = "https://contract.mexc.com/api/v1/contract/detail"

    def __init__(self):
        self._cache: Set[str] = set()
        self._cache_time: float = 0.0

    async def fetch_pairs(self):
        """Fetches the list of valid futures contracts from MEXC."""
        now = asyncio.get_event_loop().time()
        if self._cache and (now - self._cache_time < 3600):  # Cache for 1 hour
            return

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(self.MEXC_FUTURES_CONTRACTS_URL)
            r.raise_for_status()
            data = r.json()
            # We only care about USDT perpetual contracts for now
            self._cache = {
                item["symbol"]
                for item in data.get("data", [])
                if item.get("quoteCoin") == "USDT"
            }
        self._cache_time = now

    async def validate_and_convert(self, base: str, quote: str) -> Tuple[str, str, str]:
        """
        Validates a trading pair for MEXC Futures.
        Returns the pair formatted for the API (e.g., BTC_USDT).
        """
        await self.fetch_pairs()
        base_upper = base.upper()

        # MEXC Futures uses an underscore, e.g., BTC_USDT
        pair_to_check = f"{base_upper}_USDT"

        if pair_to_check in self._cache:
            return pair_to_check, base_upper, "USDT"

        raise PairNotFoundError(f"Futures contract {pair_to_check} not found on MEXC.")