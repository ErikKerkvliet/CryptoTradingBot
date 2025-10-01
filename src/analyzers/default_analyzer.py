"""Default signal analyzer using OpenAI instead of regex."""
from typing import Dict, Any, Optional
import json
from openai import OpenAI
from .abstract_analyzer import AbstractAnalyzer
from ..utils.exceptions import SignalParseError
from config.settings import settings
from ..database import TradingDatabase

from dotenv import load_dotenv

load_dotenv()

class DefaultAnalyzer(AbstractAnalyzer):
    """Parses Telegram messages into structured trading signals using OpenAI."""

    def __init__(self, db: Optional[TradingDatabase] = None):
        # Initialize OpenAI client - it will automatically use OPENAI_API_KEY from environment
        self.client = OpenAI()
        self.db = db

    async def analyze(self, message: str, channel: str) -> Dict[str, Any]:
        """
        Analyzes a message using OpenAI and returns a structured signal.
        This is the default analyzer used when no channel-specific
        analyzer is found.
        """
        buy = self._is_trade_message(message, 'BUY')
        sell = self._is_trade_message(message, 'SELL')

        if not (buy or sell):
            raise SignalParseError("Message does not appear to be a trade signal")

        # Pass channel to the parsing method
        result = await self._openai_parse(message, channel)

        if not result:
            raise SignalParseError("Failed to parse signal with DefaultAnalyzer using OpenAI")

        # The action is set inside _openai_parse now, but we can ensure it here
        if 'action' not in result or not result['action']:
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

    async def _openai_parse(self, message: str, channel: str, model: str = "gpt-5-nano") -> Optional[Dict[str, Any]]:
        """
        Uses OpenAI to parse the trading signal message into structured JSON.
        Logs the request before and updates after the call.
        """
        system_prompt = None
        prompt_id = None
        llm_response_id = -1 # Default to -1 in case of failure

        if self.db:
            # Get prompt ID from setting name
            prompt_name = settings.PROMPT_TEMPLATE_NAME
            prompt_id = self.db.get_prompt_id_by_name(prompt_name)

            # If we got an ID, fetch the template
            if prompt_id:
                system_prompt = self.db.get_prompt_template_by_id(prompt_id)
            else:
                # Fallback if name from .env is not in DB
                print(f"⚠️ Warning: Prompt template '{prompt_name}' not found. Falling back to default.")
                prompt_id = self.db.get_prompt_id_by_name('default_system_prompt')
                if prompt_id:
                    system_prompt = self.db.get_prompt_template_by_id(prompt_id)

        if not system_prompt:
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
            "stop_loss": "...",
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
        - `confidence` must be a percentage (0–100) representing how confident the LLM is that the parsed data is correct, in the format of an integer.
        - If the message contains `entries` but no `entry`, then calculate `entry` as the average of the two numbers in `entries`. 
          Example: if "entries": "9.3-9.33" then "entry" = (9.3 + 9.33) / 2 = 9.315.
        - Ensure numeric values are strings if uncertain, and arrays are used for multiple values.
        - If a field is not present in the message, return an empty string or empty array.
        - For SELL messages, `profit_target` must always be a single number or the text string "all". Never return it as an array.
        """

        user_prompt = f"Parse this trading signal:\n\n{message}"

        try:
            # Log the pending request to the database
            if self.db:
                llm_response_id = self.db.add_pending_llm_request(message, channel, model)

            response = self.client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_completion_tokens=3000
            )

            content = response.choices[0].message.content.strip()

            try:
                parsed_data = json.loads(content)

                # Validate required fields
                if not parsed_data.get("action") or not parsed_data.get("base_currency"):
                    return None

                # Add metadata to the parsed data before updating the DB
                parsed_data['raw_response'] = content
                parsed_data['prompt_id'] = prompt_id

                # Update the record with the response
                if self.db and llm_response_id != -1:
                    self.db.update_llm_response(llm_response_id, parsed_data)

                if float(parsed_data.get("confidence")) < settings.MIN_CONFIDENCE_THRESHOLD:
                    return await self._retry_prompt(message, channel, model, reason="low confidence")

                if not parsed_data.get("quote_currency"):
                    parsed_data["quote_currency"] = "USDT"

                # --- NEW: Return the database ID with the result ---
                parsed_data['llm_response_id'] = llm_response_id

                return parsed_data

            except json.JSONDecodeError as e:
                print(f"Failed to parse OpenAI response as JSON: {e}")
                print(f"Response was: {content}")
                return await self._retry_prompt(message, channel, model, reason="json error")

        except Exception as e:
            print(f"Error calling OpenAI API: {e}")
            return None

    async def _retry_prompt(self, message, channel, model, reason="low confidence"):
        # Define the model hierarchy
        model_hierarchy = ["gpt-5-nano", "gpt-5-mini", "gpt-5"]

        error_messages = {
            "low confidence": "Low confidence on {}, retrying with {}",
            "json error": "JSON parse error on {}, retrying with {}"
        }

        warning_messages = {
            "low confidence": "Warning: Low confidence on all models, proceeding with lowest confidence result.",
            "json error": "Warning: JSON parse error on all models, unable to parse message."
        }

        try:
            current_index = model_hierarchy.index(model)
        except ValueError:
            print(f"Unknown model: {model}")
            return None

        if current_index < len(model_hierarchy) - 1:
            next_model = model_hierarchy[current_index + 1]
            print(error_messages[reason].format(model, next_model))
            # Pass the channel to the retry call
            return await self._openai_parse(message, channel, next_model)

        print(warning_messages[reason])
        return None