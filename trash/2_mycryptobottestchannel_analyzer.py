"""Signal analyzer for the 'verifiedcryptotraders_real' Telegram channel."""
from typing import Dict, Any, Optional
import re

from pydantic_core.core_schema import lax_or_strict_schema

from src.analyzers.abstract_analyzer import AbstractAnalyzer
from src.utils.exceptions import SignalParseError

class MyCryptoBotTestChannelAnalyzer(AbstractAnalyzer):
    """
    A dedicated parser for messages from the 'Verified Crypto Traders®' channel.
    It uses custom regex to handle the specific signal formats of this channel.
    """

    async def analyze(self, message: str) -> Dict[str, Any]:
        """
        Analyzes a message from Verified Crypto Traders® and returns a structured signal.

        Args:
            message: The raw text message from Telegram.

        Returns:
            A dictionary containing the structured trading signal.

        Raises:
            SignalParseError: If the message cannot be parsed into a valid signal.
        """
        result = self._regex_parse(message)
        if not result:
            raise SignalParseError("Failed to parse signal with VerifiedCryptoTradersRealAnalyzer_")
        return result

    def _parse_and_clean_floats(self, text: str) -> list[float]:
        """Finds all floating-point numbers in a string and returns them as a list of floats."""
        if not text:
            return []
        # This regex is designed to find numbers, including those with decimal points.
        # It handles cases where numbers are separated by commas, spaces, or newlines.
        found_numbers = re.findall(r'[0-9]+\.?[0-9]*', text)
        return [float(num) for num in found_numbers]

    def _regex_parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Regex-based parser for "Verified Crypto Traders®" signals.
        Builds a structured dictionary with confidence set to 100.
        """
        t = text

        out = {
            "action": None,
            "base_currency": None,
            "quote_currency": "USDT", # Defaulting to USDT as it's most common
            "entry_price": None,
            "entry_price_range": None,
            "take_profit_target": None,
            "stop_loss": None,
            "leverage": None,
            "confidence": 100,
        }

        # --- Action (BUY/SELL) ---
        if re.search(r'LONG|Type - Long', t, re.I):
            out["action"] = "BUY"
        elif re.search(r'SHORT|Type - Short', t, re.I):
            out["action"] = "SELL"
        elif re.search(r'entry targets achieved', t, re.I) or re.search(r'Profit:', t, re.I):
            out["action"] = "SELL"
        elif re.search(r'Take-?Profit target', t, re.I) or re.search(r'Profit:', t, re.I):
            out["action"] = "SELL"

        # --- Pair (e.g., #BIO/USDT, $SOMI, ADA / USDT) ---
        pair_match = re.search(r'#([A-Z0-9]+)\/([A-Z0-9]+)|Coin #([A-Z0-9]+)\/([A-Z0-9]+)|\$([A-Z0-9]+)|TRADE - ([A-Z0-9]+)\s*\/\s*([A-Z0-9]+)', t, re.I)
        if pair_match:
            if pair_match.group(1) and pair_match.group(2): # #BIO/USDT
                out["base_currency"] = pair_match.group(1).upper()
                out["quote_currency"] = pair_match.group(2).upper()
            elif pair_match.group(3) and pair_match.group(4): # Coin #BIO/USDT
                out["base_currency"] = pair_match.group(3).upper()
                out["quote_currency"] = pair_match.group(4).upper()
            elif pair_match.group(5): # $SOMI
                out["base_currency"] = pair_match.group(5).upper()
            elif pair_match.group(6) and pair_match.group(7): # TRADE - ADA / USDT
                out["base_currency"] = pair_match.group(6).upper()
                out["quote_currency"] = pair_match.group(7).upper()




        # --- Leverage ---
        leverage_match = re.search(r'Leverage\s*:\s*Cross\s*(\d+)[x×]|Leverage:\s*Cross(\d+)[xX]|Leverage-\s*(\d+)[xX]', t, re.I)
        if leverage_match:
            leverage_val = next((g for g in leverage_match.groups() if g is not None), None)
            if leverage_val:
                out["leverage"] = f"Cross {leverage_val}x"


        # --- Entry Price / Range ---
        entry_match = re.search(r'(?:Entry|Entries|Buy Zone)\s*[:\-]?\s*([0-9.]+\s*-\s*[0-9.]+)|Entry Market Price\s*([0-9.]+)', t, re.I)
        if entry_match:
            if entry_match.group(1): # Range e.g., "0.1845 - 0.1790"
                prices = self._parse_and_clean_floats(entry_match.group(1))
                if len(prices) == 2:
                    out["entry_price_range"] = sorted(prices)
            elif entry_match.group(2): # Single market price e.g., "0.87"
                out["entry_price"] = float(entry_match.group(2))

        # --- Take Profit Targets ---
        # Look for a block of text starting with "Take Profit" or "Targets"
        tp_block_match = re.search(r'(Take Profit|Targets|TP\s*\(?)([\s\S]+?)(?=Stoploss|Stop Loss|SL\s*⛔️|⭕)', t, re.I)
        if tp_block_match:
            tp_text = tp_block_match.group(2)
            targets = self._parse_and_clean_floats(tp_text)
            if targets:
                out["take_profit_targets"] = sorted(targets)


        # --- Stop Loss ---
        sl_match = re.search(r'(?:Stoploss|Stop Loss|SL\s*⛔️)\s*[:\(]?\s*([0-9.]+)', t, re.I)
        if sl_match:
            out["stop_loss"] = float(sl_match.group(1))

        # --- Final Validation ---
        # A valid signal must have at least an action and a base currency.
        if out["action"] and out["base_currency"]:
            return out

        return None