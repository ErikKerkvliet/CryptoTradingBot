"""Pair validation and conversion utilities for Kraken."""
from typing import Tuple, Optional, Set
from .utils.exceptions import PairNotFoundError
import httpx
import asyncio


class PairValidator:
    """
    Validates symbol pairs against the Kraken REST API.
    It automatically converts common crypto symbols to Kraken's format (e.g., BTC -> XBT)
    and prefers USDC over USDT as a quote currency.
    """

    KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"

    # Mapping of common cryptocurrency symbols to Kraken's specific symbols.
    # Kraken often uses an 'X' prefix for cryptocurrencies and a 'Z' for fiat.
    KRAKEN_NAME_MAPPING = {
        "BTC": "XBT",
        "DOGE": "XDG",
        # ETH is commonly used as-is, but XETH is its official ticker
        "ETH": "XETH",
    }

    def __init__(self):
        self._cache: dict = {}
        self._cache_time: float = 0.0

    async def fetch_pairs(self) -> dict:
        """
        Fetches the list of valid trading pairs from Kraken's API.
        The result is cached for 1 hour to avoid excessive API calls.
        """
        now = asyncio.get_event_loop().time()
        # Cache for 1 hour (3600 seconds)
        if self._cache and (now - self._cache_time < 3600):
            return self._cache

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(self.KRAKEN_ASSET_PAIRS_URL)
            r.raise_for_status()
            data = r.json()
            self._cache = data.get("result", {})
            self._cache_time = now
            return self._cache

    async def validate_and_convert(self, base: str, quote: str) -> Tuple[str, str]:
        """
        Validates a trading pair against Kraken's available pairs. It applies necessary
        name conversions (like BTC->XBT) and handles the USDT->USDC preference.

        Raises:
            PairNotFoundError: If no valid trading pair can be found after conversion.

        Returns:
            A tuple containing the validated and converted (base, quote) pair names
            that can be used for trading on Kraken.
        """
        base_upper = base.upper()
        quote_upper = quote.upper()

        # Step 1: Apply Kraken's specific name mapping
        kraken_base = self.KRAKEN_NAME_MAPPING.get(base_upper, base_upper)
        kraken_quote = self.KRAKEN_NAME_MAPPING.get(quote_upper, quote_upper)

        # Step 2: Prefer USDC over USDT. We will try USDC first.
        # preferred_quote = "USDC" if kraken_quote == "USDT" else kraken_quote
        preferred_quote = "EUR"

        all_pairs = await self.fetch_pairs()

        # Step 3: Attempt to find a match with the preferred quote currency (USDC)
        # We check against both the original name and the mapped name.
        possible_bases: Set[str] = {base_upper, kraken_base}
        
        for b in possible_bases:
            # Check for a direct match (e.g., "BTC/USDC" or "XBTUSDC")
            if self._find_matching_pair(b, preferred_quote, all_pairs):
                return kraken_base, preferred_quote

        # Step 4: If no USDC pair was found and the original was USDT, try USDT
        if preferred_quote == "USDC" and kraken_quote == "USDT":
            for b in possible_bases:
                if self._find_matching_pair(b, "USDT", all_pairs):
                    return kraken_base, "USDT"

        raise PairNotFoundError(f"Pair {base}/{quote} not found on Kraken, even after checking for alternatives like {kraken_base}/{preferred_quote}")

    def _find_matching_pair(self, base: str, quote: str, all_pairs: dict) -> bool:
        """
        Helper function to check if a base/quote combination exists in Kraken's pair list.
        It checks against 'wsname' (e.g., 'XBT/USD') and 'altname' (e.g., 'XBTUSD').
        """
        # Format for wsname (e.g., "XBT/USDC")
        ws_pair = f"{base}/{quote}"
        # Format for altname (e.g., "XBTUSDC")
        alt_pair = f"{base}{quote}"

        for info in all_pairs.values():
            if info.get("wsname", "").upper() == ws_pair or info.get("altname", "").upper() == alt_pair:
                return True
        return False