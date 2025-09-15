"""Default signal analyzer using OpenAI instead of regex."""
from typing import Dict, Any, Optional
import json
from openai import OpenAI
from .abstract_analyzer import AbstractAnalyzer
from ..utils.exceptions import SignalParseError
from dotenv import load_dotenv

load_dotenv()

class DefaultAnalyzer(AbstractAnalyzer):
    """Parses Telegram messages into structured trading signals using OpenAI."""

    def __init__(self):
        # Initialize OpenAI client - it will automatically use OPENAI_API_KEY from environment
        self.client = OpenAI()

    async def analyze(self, message: str) -> Dict[str, Any]:
        """
        Analyzes a message using OpenAI and returns a structured signal.
        This is the default analyzer used when no channel-specific
        analyzer is found.
        """
        buy = self._is_trade_message(message, 'BUY')
        sell = self._is_trade_message(message, 'SELL')

        if not (buy or sell):
            raise SignalParseError("Message does not appear to be a trade signal")

        result = await self._openai_parse(message)

        if not result:
            raise SignalParseError("Failed to parse signal with DefaultAnalyzer using OpenAI")

        result['action'] = 'BUY' if buy else 'SELL'

        return result

    @staticmethod
    def _is_trade_message(message: str, message_type: str) -> bool:
        """Check if message appears to be a trading signal."""
        message_lower = message.lower()

        if message_type == 'BUY':
            keywords = [
                ('entry', 'entries', 'enter'),
                ('target',),
                ('buy', 'long'),
                ('leverage',),
                ('stop', 'loss', 'sl')
            ]
        elif message_type == 'SELL':
            keywords = [
                ('take', 'profit'),
                ('short', 'sell'),
                ('achieved',),
                ('period',),
                ('%',),
                ('✅',),
            ]
        else:
            return False

        substr_matches = sum(
            any(keyword in message_lower for keyword in group)
            for group in keywords
        )

        if 'all entry targets achieved' in message_lower:
            if message_type == 'SELL':
                substr_matches += 3
            if message_type == 'BUY':
                return False

        return substr_matches > 2

    async def _openai_parse(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Uses OpenAI to parse the trading signal message into structured JSON.
        """
        system_prompt = """You are a cryptocurrency trading signal parser. Your job is to extract structured information from trading signals and return it as JSON.

return the following data "action", "base_currency", "quote_currency", "entry_price", "entry_price_range", "take_profit_targets", "stop_loss", "leverage"

Return ONLY the JSON object, no other text."""

        user_prompt = f"Parse this trading signal:\n\n{message}"

        try:
            response = self.client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=3000,
                temperature=0.1
            )

            # Extract the JSON from the response
            content = response.choices[0].message.content.strip()

            # Try to parse the JSON
            try:
                parsed_data = json.loads(content)

                # Validate required fields
                if not parsed_data.get("action") or not parsed_data.get("base_currency"):
                    return None

                # Ensure confidence is set to 100
                parsed_data["confidence"] = 100

                # Ensure quote_currency defaults to USDT if not set
                if not parsed_data.get("quote_currency"):
                    parsed_data["quote_currency"] = "USDT"

                return parsed_data

            except json.JSONDecodeError as e:
                print(f"Failed to parse OpenAI response as JSON: {e}")
                print(f"Response was: {content}")
                return None

        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return None