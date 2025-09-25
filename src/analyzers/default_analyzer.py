"""Default signal analyzer using OpenAI instead of regex."""
from typing import Dict, Any, Optional
import json
from openai import OpenAI
from .abstract_analyzer import AbstractAnalyzer
from ..utils.exceptions import SignalParseError
from config.settings import settings

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

    async def _openai_parse(self, message: str, model: str = "gpt-5-nano") -> Optional[Dict[str, Any]]:
        """
        Uses OpenAI to parse the trading signal message into structured JSON.
        """
        system_prompt = """
        You are a cryptocurrency trading signal parser. 
        Your task is to extract structured information from trading signals and return it as JSON.

        Rules:
        - Output ONLY a valid JSON object, no other text.
        - For BUY messages, always return the following fields:
          {
            "action": "buy",
            "base_currency": "...",
            "quote_currency": "...",
            "leverage": "...",
            "entries": "...",
            "entry": "...",
            "targets": ["...", "...", "..."],
            "stoploss": "...",
            "confidence": "..."
          }
        - For SELL messages, always return the following fields:
          {
            "action": "sell",
            "base_currency": "...",
            "quote_currency": "...",
            "profit_target": "...",
            "profit": "...",
            "period: "...",
            "confidence": "..."
          }
        - `confidence` must be a percentage (0–100) representing how confident the LLM is that the parsed data is correct, in the format of an integer or float string (e.g. "85" or "92.5").
        - If the message contains `entries` but no `entry`, then calculate `entry` as the average of the two numbers in `entries`. 
          Example: if "entries": "9.3-9.33" then "entry" = (9.3 + 9.33) / 2 = 9.315.
        - Ensure numeric values are strings if uncertain, and arrays are used for multiple values.
        - If a field is not present in the message, return an empty string or empty array.
        - For SELL messages, `profit_target` must always be a single number or the text string "all". Never return it as an array.
        """

        user_prompt = f"Parse this trading signal:\n\n{message}"

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_completion_tokens=3000            )

            # Extract the JSON from the response
            content = response.choices[0].message.content.strip()

            # Try to parse the JSON
            try:
                parsed_data = json.loads(content)

                # Validate required fields
                if not parsed_data.get("action") or not parsed_data.get("base_currency"):
                    return None

                if float(parsed_data.get("confidence")) < settings.MIN_CONFIDENCE_THRESHOLD:
                    parsed_data = await self._retry_prompt(message, model, reason="low confidence")
                # Ensure quote_currency defaults to USDT if not set
                if not parsed_data.get("quote_currency"):
                    parsed_data["quote_currency"] = "USDT"

                parsed_data['raw_response'] = content

                return parsed_data

            except json.JSONDecodeError as e:
                print(f"Failed to parse OpenAI response as JSON: {e}")
                print(f"Response was: {content}")
                return await self._retry_prompt(message, model, reason="json error")

        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return None

    async def _retry_prompt(self, message, model, reason="low confidence"):
        # Define the model hierarchy
        model_hierarchy = ["gpt-5-nano", "gpt-5-mini", "gpt-5-codex", "gpt-5"]

        # Error messages for different reasons
        error_messages = {
            "low confidence": "Low confidence on {}, retrying with {}",
            "json error": "JSON parse error on {}, retrying with {}"
        }

        # Warning messages for when all models fail
        warning_messages = {
            "low confidence": "Warning: Low confidence on all models, proceeding with lowest confidence result.",
            "json error": "Warning: JSON parse error on all models, unable to parse message."
        }

        try:
            current_index = model_hierarchy.index(model)
        except ValueError:
            print(f"Unknown model: {model}")
            return None

        # If we're not at the last model, try the next one
        if current_index < len(model_hierarchy) - 1:
            next_model = model_hierarchy[current_index + 1]
            print(error_messages[reason].format(model, next_model))
            return await self._openai_parse(message, next_model)

        # If we're at the last model, print warning and return None
        print(warning_messages[reason])
        return None
