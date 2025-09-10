"""Pair validation and conversion utilities for Kraken and MEXC."""
from typing import Tuple, Set
from .utils.exceptions import PairNotFoundError
import httpx
import asyncio


class PairValidator:
    """
    Validates symbol pairs against the selected exchange's REST API.
    It handles exchange-specific formatting (e.g., BTC -> XBT for Kraken).
    """

    KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
    MEXC_EXCHANGE_INFO_URL = "https://api.mexc.com/api/v3/exchangeInfo"

    KRAKEN_NAME_MAPPING = {
        "BTC": "XBT",
        "DOGE": "XDG",
        "ETH": "XETH",
    }

    def __init__(self, exchange: str):
        self.exchange = exchange.upper()
        self._cache: dict = {}
        self._cache_time: float = 0.0
        self._mexc_symbols: Set[str] = set()


    async def fetch_pairs(self):
        """
        Fetches the list of valid trading pairs from the configured exchange's API.
        The result is cached for 1 hour.
        """
        now = asyncio.get_event_loop().time()
        if self._cache and (now - self._cache_time < 3600):
            return

        async with httpx.AsyncClient(timeout=10) as client:
            if self.exchange == "KRAKEN":
                r = await client.get(self.KRAKEN_ASSET_PAIRS_URL)
                r.raise_for_status()
                data = r.json()
                self._cache = data.get("result", {})
            elif self.exchange == "MEXC":
                r = await client.get(self.MEXC_EXCHANGE_INFO_URL)
                r.raise_for_status()
                data = r.json()
                self._cache = {item['symbol']: item for item in data.get("symbols", [])}
                self._mexc_symbols = {item['symbol'] for item in data.get("symbols", [])}

        self._cache_time = now

    async def validate_and_convert(self, base: str, quote: str) -> Tuple[str, str, str]:
        """
        Validates a trading pair against the exchange's available pairs.

        Returns:
            A tuple containing (formatted_pair, base, quote)
        """
        await self.fetch_pairs()
        base_upper = base.upper()
        quote_upper = quote.upper()

        if self.exchange == "KRAKEN":
            return await self._validate_for_kraken(base_upper, quote_upper)
        elif self.exchange == "MEXC":
            return await self._validate_for_mexc(base_upper, quote_upper)
        else:
            raise ValueError(f"Unsupported exchange for validation: {self.exchange}")

    async def _validate_for_kraken(self, base: str, quote: str) -> Tuple[str, str, str]:
        """Handles Kraken-specific validation and conversion."""
        kraken_base = self.KRAKEN_NAME_MAPPING.get(base, base)
        kraken_quote = self.KRAKEN_NAME_MAPPING.get(quote, quote)

        preferred_quotes = ["USDC", "USDT", "EUR", "USD"]
        if quote in preferred_quotes:
            # Try specified quote first, then fall back
            quotes_to_try = [quote] + [q for q in preferred_quotes if q != quote]
        else:
            quotes_to_try = preferred_quotes

        for q in quotes_to_try:
            ws_pair = f"{kraken_base}/{q}"
            alt_pair = f"{kraken_base}{q}"
            for info in self._cache.values():
                if info.get("wsname", "").upper() == ws_pair or info.get("altname", "").upper() == alt_pair:
                    return ws_pair, kraken_base, q

        raise PairNotFoundError(f"Pair {base}/{quote} not found on Kraken with any preferred quote.")


    async def _validate_for_mexc(self, base: str, quote: str) -> Tuple[str, str, str]:
        """Handles MEXC-specific validation."""

        # On MEXC, USDT is the most common quote currency.
        preferred_quotes = ["USDT", "USDC", "BTC", "ETH"]
        if quote in preferred_quotes:
             quotes_to_try = [quote] + [q for q in preferred_quotes if q != quote]
        else:
            quotes_to_try = [quote] + preferred_quotes

        for q in quotes_to_try:
            pair_str = f"{base}{q}"
            if pair_str in self._mexc_symbols:
                return pair_str, base, q

        raise PairNotFoundError(f"Pair {base}/{quote} not found on MEXC.")