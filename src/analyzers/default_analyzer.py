"""Default signal analyzer using regex."""
from typing import Dict, Any, Optional
import re
from .abstract_analyzer import AbstractAnalyzer
from ..utils.exceptions import SignalParseError

class DefaultAnalyzer(AbstractAnalyzer):
    """Parses Telegram messages into structured trading signals using regex."""

    async def analyze(self, message: str) -> Dict[str, Any]:
        """
        Analyzes a message using regex and returns a structured signal.
        This is the default analyzer used when no channel-specific
        analyzer is found.
        """
        result = self._regex_parse(message)
        if not result:
            raise SignalParseError("Failed to parse signal with DefaultAnalyzer")
        return result

    def _regex_parse(self, text: str) -> Optional[Dict[str, Any]]:
        """Regex-based parser that builds structured JSON with confidence=100."""
        t = text

        out = {
            "action": None,
            "base_currency": None,
            "quote_currency": None,
            "entry_price": None,
            "entry_price_range": None,
            "take_profit_levels": None,
            "stop_loss": None,
            "leverage": None,
            "confidence": 100,  # always 100 now
        }

        # action
        if re.search(r'Position:\s*LONG', t, re.I):
            out["action"] = "BUY"
        elif re.search(r'Position:\s*SHORT', t, re.I):
            out["action"] = "SELL"
        elif re.search(r'Take-?Profit target', t, re.I) or re.search(r'Profit:', t, re.I):
            out["action"] = "SELL"

        # pair
        m = re.search(r'#?([A-Za-z0-9]+)\/([A-Za-z0-9]+)', t)
        if m:
            out["base_currency"] = m.group(1).upper()
            out["quote_currency"] = m.group(2).upper()

        # leverage
        mlev = re.search(r'Leverage:\s*([^\n\r]+)', t, re.I)
        if mlev:
            out["leverage"] = mlev.group(1).strip()

        # entry price range
        mentry_range = re.search(r'Entries?:\s*([0-9]*\.?[0-9]+)\s*-\s*([0-9]*\.?[0-9]+)', t, re.I)
        if mentry_range:
            out["entry_price_range"] = [float(mentry_range.group(1)), float(mentry_range.group(2))]
        else:
            # single entry
            mentry_single = re.search(r'Entries?:\s*([0-9]*\.?[0-9]+)', t, re.I)
            if mentry_single:
                out["entry_price"] = float(mentry_single.group(1))

        # targets
        targets_m = re.search(r'Targets?:\s*([^\n\r]+)', t, re.I)
        if targets_m:
            nums = re.findall(r'\d+\.\d+|\d+', targets_m.group(1))
            if nums:
                out["take_profit_levels"] = [float(n) for n in nums]
        else:
            tp_idx = re.search(r'Take-?Profit target[s]?\s*(\d+)', t, re.I)
            if tp_idx:
                out["take_profit_levels"] = int(tp_idx.group(1))

        # stop loss
        sl_m = re.search(r'Stop Loss:\s*([0-9]*\.?[0-9]+)', t, re.I)
        if sl_m:
            out["stop_loss"] = float(sl_m.group(1))

        if out["action"] and out["base_currency"]:
            return out
        return None