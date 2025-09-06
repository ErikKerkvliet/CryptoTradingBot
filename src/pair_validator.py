"""Pair validation and conversion utilities for Kraken."""
from typing import Tuple, Optional
from .utils.exceptions import PairNotFoundError
import httpx
import asyncio


class PairValidator:
    """Validates symbol pairs against Kraken REST API and converts USDT->USDC."""

    KRAKEN_ASSET_PAIRS = "https://api.kraken.com/0/public/AssetPairs"

    def __init__(self):
        self._cache = {}

    async def fetch_pairs(self) -> dict:
        if self._cache:
            return self._cache
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(self.KRAKEN_ASSET_PAIRS)
            r.raise_for_status()
            data = r.json()
            self._cache = data.get("result", {})
            return self._cache

    async def validate_and_convert(self, base: str, quote: str) -> Tuple[str, str]:
        """Validate pair on Kraken and convert USDT->USDC if necessary. Returns (base, quote_on_kraken).

        Raises PairNotFoundError when no valid conversion exists.
        """
        quote = quote.upper()
        base = base.upper()
        if quote == "USDT":
            quote = "USDC"
        pairs = await self.fetch_pairs()
        # Kraken asset pair keys vary; check if any pair contains base and quote
        for pair_name, info in pairs.items():
            alt = info.get("altname", "").upper()
            wsname = info.get("wsname", "").upper()
            if f"{base}/{quote}" in (alt, wsname):
                return base, quote
        raise PairNotFoundError(f"Pair {base}/{quote} not found on Kraken")