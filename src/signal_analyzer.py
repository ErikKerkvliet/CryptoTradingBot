"""SignalAnalyzer uses OpenAI to parse text signals into structured objects."""
from __future__ import annotations
from typing import Dict, Any, Optional, List, Union
from openai import OpenAI
import asyncio
import re
import json
from .utils.exceptions import SignalParseError


class SignalAnalyzer:
    """Parses Telegram messages into structured trading signals using OpenAI completion as helper.

    The openai API key must be set in the environment (see config.settings)
    """

    PROMPT_TEMPLATE = (
        "Parse the following trading signal into JSON with keys: action (BUY/SELL), base_currency, "
        "quote_currency, entry_price or entry_price_range (list), take_profit_levels (list), stop_loss, "
        "leverage (optional), confidence (0-100). The 'confidence' field should represent the LLM's own "
        "estimate of how confident it is that the parsed information is correct. If a field is not present, use null. "
        "Return only valid JSON.\n\n"
    )

    def __init__(self, openai_api_key: str):
        self.client = OpenAI(api_key=openai_api_key)

    async def analyze(self, message: str) -> Dict[str, Any]:
        # Fast heuristic attempt first (regex). If low-confidence or ambiguous, fall back to OpenAI.
        result = self._regex_parse(message)
        if result and result.get("confidence", 0) >= 85:
            return result
        # else call OpenAI (async call)
        parsed = await self._call_openai(message)
        if not parsed:
            raise SignalParseError("Failed to parse signal")
        return parsed

    def _regex_parse(self, text: str) -> Optional[Dict[str, Any]]:
        t = text.upper()
        out = {
            "action": None,
            "base_currency": None,
            "quote_currency": None,
            "entry_price": None,
            "entry_price_range": None,
            "take_profit_levels": None,
            "stop_loss": None,
            "leverage": None,
            "confidence": 0,
        }
        # action
        if any(k in t for k in ("LONG", "BUY")):
            out["action"] = "BUY"
        elif any(k in t for k in ("SHORT", "SELL")):
            out["action"] = "SELL"

        # pair e.g. #BTC/USDT or BTC/USDT
        m = re.search(r"([A-Z0-9]+)[/\\\\]?(USDT|USDC|USD|EUR|BTC|ETH)", t)
        if m:
            out["base_currency"] = m.group(1)
            out["quote_currency"] = m.group(2)

        # leverage
        mlev = re.search(r"(\d{1,3})X", t)
        if mlev:
            out["leverage"] = int(mlev.group(1))

        # entry range
        mentry_range = re.search(r"ENTRY[:\s]+(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", t)
        if mentry_range:
            a = float(mentry_range.group(1))
            b = float(mentry_range.group(2))
            out["entry_price_range"] = [min(a, b), max(a, b)]

        mentry_single = re.search(r"ENTRY[:\s]+(\d+(?:\.\d+)?)", t)
        if mentry_single and not out["entry_price_range"]:
            out["entry_price"] = float(mentry_single.group(1))

        # TP
        mtp = re.search(r"TP[:\s]+([0-9\.,\s]+)", t)
        if not mtp:
            mtp = re.search(r"TARGETS?[:\s]+([0-9\.,\s]+)", t)
        if mtp:
            nums = re.findall(r"\d+(?:\.\d+)?", mtp.group(1))
            out["take_profit_levels"] = [float(x) for x in nums]

        # SL
        msl = re.search(r"SL[:\s]+(\d+(?:\.\d+)?)", t)
        if msl:
            out["stop_loss"] = float(msl.group(1))

        # crude confidence
        confidence = 40
        if out["action"]:
            confidence += 15
        if out["base_currency"] and out["quote_currency"]:
            confidence += 20
        if out["take_profit_levels"] or out["stop_loss"]:
            confidence += 10
        if out["entry_price"] or out["entry_price_range"]:
            confidence += 15
        out["confidence"] = min(100, confidence)

        if out["action"] and out["base_currency"]:
            return out
        return None

    async def _call_openai(self, message: str) -> Optional[Dict[str, Any]]:
        prompt = self.PROMPT_TEMPLATE + "Signal:\n" + message + "\n\nReturn JSON only."
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model="gpt-5-nano",
                    messages=[
                        {"role": "system", "content": "You are a trading signal parser. Return only valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=3000,
                    temperature=1
                )
            )

            text = response.choices[0].message.content.strip()
            # sometimes returns code block - extract JSON
            m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
            if m:
                text = m.group(1)
            data = json.loads(text)
            return data
        except Exception as e:
            print(f"OpenAI API error: {e}")
            return None