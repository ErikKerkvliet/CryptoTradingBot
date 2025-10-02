# src/take_profit_decision_manager.py

"""
Uses an LLM to intelligently select the best take-profit target from a list.
"""
from typing import Dict, Any, Tuple, Optional
import json
from openai import OpenAI
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class TakeProfitDecisionManager:
    """
    Analyzes a trading signal's potential take-profit targets using an LLM
    to select the most optimal one based on risk and market context.
    """

    PROMPT_NAME = "take_profit_selector_prompt"

    def __init__(self, settings_instance, db):  # <-- ADD db as a parameter
        self.settings = settings_instance
        self.db = db  # <-- STORE the database instance
        self.client = OpenAI(api_key=self.settings.OPENAI_API_KEY)
        self.model = self.settings.LLM_TP_SELECTOR_MODEL

    async def select_best_target(self, parsed_signal: Dict[str, Any]) -> Tuple[
        Optional[float], Optional[int], Optional[str]]:
        """
        Calls the LLM to select the best target and returns the choice.

        Returns:
            A tuple of (chosen_target_value, chosen_target_index, reasoning).
            Returns (None, None, None) on failure.
        """
        # 1. Fetch the prompt template from the database
        prompt_template = self.db.get_prompt_template(self.PROMPT_NAME)

        if not prompt_template:
            logger.error(f"Could not find prompt '{self.PROMPT_NAME}' in the database. Aborting TP selection.")
            return None, None, None

        # 2. Prepare the data to be injected into the template
        entry_price = parsed_signal.get('entry_price') or (sum(parsed_signal.get('entry_price_range', [0, 0])) / 2)

        prompt_data = {
            "pair": f"{parsed_signal.get('base_currency', 'N/A')}/{parsed_signal.get('quote_currency', 'USDT')}",
            "action": parsed_signal.get('action', '').upper(),
            "entry_price": entry_price,
            "stop_loss": parsed_signal.get('stop_loss'),
            "targets": parsed_signal.get('targets', [])
        }

        # 3. Format the final prompt with the signal's data
        system_prompt = prompt_template.format(**prompt_data)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            content = response.choices[0].message.content

            # Parse the JSON response
            data = json.loads(content)

            reasoning = data.get("reasoning")
            index = data.get("chosen_target_index")
            value = data.get("chosen_target_value")

            # Basic validation
            if isinstance(index, int) and isinstance(value, (float, int)):
                return float(value), int(index), reasoning
            else:
                logger.warning("LLM for TP selection returned invalid data types.")
                return None, None, None

        except Exception as e:
            logger.error(f"Error calling OpenAI for TP selection: {e}")
            logger.error("Falling back to default static TP selection logic.")
            return None, None, None