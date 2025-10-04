"""
Centralized order placement logic for the trading bot.
"""
from typing import Dict, Any, Optional
import httpx
from src.database import TradingDatabase
from src.utils.exceptions import InsufficientBalanceError
from src.utils.logger import setup_logger

class PlaceOrder:
    """
    Handles the logic for placing buy and sell orders, including validation,
    database logging, and standardized error handling.
    """

    def __init__(self, db: TradingDatabase):
        """
        Initializes the PlaceOrder manager.

        Args:
            db: An instance of the TradingDatabase.
        """
        self.db = db
        # Set up logger in the same way as main.py
        self.logger = setup_logger(__name__)

    async def execute(
        self,
        trader: Any,
        pair: str,
        side: str,
        volume: float,
        ordertype: str,
        price: Optional[float] = None,
        telegram_channel: Optional[str] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit_target: Optional[int] = None,
        leverage: int = 0,
        targets: Optional[list] = None,
        llm_response_id: Optional[int] = None,
        llm_tp_reasoning: Optional[str] = None,
        original_buy_trade_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Executes a trade order by validating inputs, calling the specific
        trader's execution method, and logging the result.

        Args:
            trader: The trader instance (e.g., KrakenTrader, DryRunTrader).
                    It must have a `_execute_order` method.
            original_buy_trade_id (Optional[int]): The ID of the original buy trade if this is a sell.

        Returns:
            A dictionary with the order result, or None if the order failed.
        """
        try:
            self.logger.info(f"Attempting to place order: {side.upper()} {volume:.6f} {pair} at {price or 'market'}")
            if telegram_channel:
                self.logger.info(f"   Source Channel: {telegram_channel}")

            # --- Pre-flight Checks ---
            if volume <= 0:
                self.logger.error("Order failed: Volume must be positive.")
                return None
            if ordertype.lower() == "limit" and price is None:
                self.logger.error("Order failed: Price must be specified for limit orders.")
                return None

            # Delegate the actual API call to the trader instance
            # The trader instance is responsible for its specific API format.
            order_result = await trader._execute_order(
                pair=pair,
                side=side,
                volume=volume,
                ordertype=ordertype,
                price=price,
                telegram_channel=telegram_channel,
                leverage=leverage
            )

            if not order_result or order_result.get("status") in ["failed", "error"]:
                self.logger.error(f"Order placement failed by trader. Result: {order_result}")
                return None

            self.logger.info(f"✅ Order executed successfully via {trader.exchange}. Result: {order_result}")

            # --- Database Logging ---
            # For a 'buy' order, we create a new trade record.
            # For a 'sell' order, we update the original 'buy' trade to 'closed'.
            if side.lower() == "buy":
                trade_data = {
                    "base_currency": order_result["base_currency"],
                    "quote_currency": order_result["quote_currency"],
                    "telegram_channel": telegram_channel,
                    "volume": volume,
                    "price": order_result.get("price", price), # Use price from result if available
                    "ordertype": ordertype,
                    "status": order_result.get("status", "open"),
                    "take_profit": take_profit,
                    "stop_loss": stop_loss,
                    "take_profit_target": take_profit_target,
                    "leverage": str(leverage),
                    "targets": targets,
                    "llm_response_id": llm_response_id,
                    "llm_tp_reasoning": llm_tp_reasoning
                }
                self.db.add_trade(trade_data)
                self.logger.info("New BUY trade has been logged to the database.")

            elif side.lower() == "sell" and original_buy_trade_id is not None:
                close_price = order_result.get("price", price)
                if close_price:
                    self.db.update_trade_status(original_buy_trade_id, 'closed', close_price=close_price)
                    self.logger.info(
                        f"Original BUY trade (ID: {original_buy_trade_id}) has been marked as 'closed' at price {close_price}.")
                else:
                    self.db.update_trade_status(original_buy_trade_id, 'closed')
                    self.logger.warning(
                        f"Sell order succeeded but no price was returned. BUY trade (ID: {original_buy_trade_id}) closed without P&L.")

            return order_result

        except InsufficientBalanceError as e:
            self.logger.warning(f"Order failed due to insufficient balance: {e}")
            return None
        except httpx.HTTPStatusError as e:
            self.logger.error(f"HTTP error placing order: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            self.logger.error(f"Network error placing order: {e}")
            return None
        except Exception as e:
            self.logger.exception(f"An unexpected critical error occurred during order placement: {e}")
            return None