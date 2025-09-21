"""
Sell Decision Manager - Decides whether to execute sell trades based on various criteria.

This class analyzes market conditions, trade history, and risk parameters to make
intelligent sell decisions. It's designed to be integrated into the trading system
when ready, without affecting current functionality.
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from enum import Enum
import asyncio


class SellDecision(Enum):
    """Possible sell decision outcomes."""
    SELL = "sell"
    HOLD = "hold"
    PARTIAL_SELL = "partial_sell"
    BLOCK = "block"


class SellReason(Enum):
    """Reasons for sell decisions."""
    PROFIT_TARGET = "profit_target_reached"
    STOP_LOSS = "stop_loss_triggered"
    TRAILING_STOP = "trailing_stop_triggered"
    TIME_BASED = "time_based_exit"
    MARKET_CONDITIONS = "unfavorable_market_conditions"
    RISK_MANAGEMENT = "risk_management"
    SIGNAL_CONFIDENCE = "low_signal_confidence"
    LOSS_PREVENTION = "loss_prevention"
    INSUFFICIENT_PROFIT = "insufficient_profit"
    VOLATILITY = "high_volatility"


class SellDecisionManager:
    """
    Manages sell decisions based on multiple criteria including profit/loss,
    market conditions, time factors, and risk management rules.
    """

    def __init__(self, settings=None):
        """
        Initialize the SellDecisionManager with configuration settings.

        Args:
            settings: Configuration object containing trading parameters
        """
        self.settings = settings

        # Default configuration - can be overridden by settings
        self.config = {
            # Profit/Loss thresholds
            "min_profit_percentage": 0.5,  # Minimum profit % to consider selling
            "max_loss_percentage": 5.0,  # Maximum loss % before forced sell
            "trailing_stop_percentage": 2.0,  # Trailing stop loss %

            # Time-based rules
            "max_hold_hours": 24,  # Maximum hours to hold a position
            "min_hold_minutes": 5,  # Minimum minutes before allowing sell

            # Market condition factors
            "volatility_threshold": 10.0,  # High volatility threshold %
            "volume_drop_threshold": 50.0,  # Volume drop threshold %

            # Risk management
            "max_drawdown_percentage": 10.0,  # Maximum portfolio drawdown %
            "position_size_factor": 0.1,  # Factor for position sizing consideration

            # Signal confidence
            "min_sell_confidence": 70,  # Minimum confidence for sell signals
            "confidence_boost_profit": 5.0,  # Profit % that boosts confidence requirement
        }

        # Update config with settings if provided
        if settings:
            self._update_config_from_settings(settings)

    def _update_config_from_settings(self, settings):
        """Update configuration from settings object."""
        try:
            # Map settings to internal config
            if hasattr(settings, 'MIN_PROFIT_PERCENTAGE'):
                self.config['min_profit_percentage'] = settings.MIN_PROFIT_PERCENTAGE
            if hasattr(settings, 'MAX_DAILY_TRADES'):
                # Use max daily trades as a risk factor
                self.config['risk_factor'] = 1.0 / max(1, settings.MAX_DAILY_TRADES)
        except Exception as e:
            print(f"Warning: Error updating config from settings: {e}")

    async def should_sell(
            self,
            signal_data: Dict[str, Any],
            last_buy_trade: Dict[str, Any],
            current_price: float,
            market_data: Optional[Dict[str, Any]] = None,
            portfolio_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[SellDecision, List[SellReason], Dict[str, Any]]:
        """
        Determine whether to execute a sell trade based on comprehensive analysis.

        Args:
            signal_data: Parsed signal data from analyzer
            last_buy_trade: Last buy trade data for this pair/channel
            current_price: Current market price
            market_data: Optional market condition data
            portfolio_data: Optional portfolio performance data

        Returns:
            Tuple of (decision, reasons, additional_data)
        """
        reasons = []
        additional_data = {}

        if not last_buy_trade:
            return SellDecision.BLOCK, [SellReason.LOSS_PREVENTION], {
                "message": "No previous buy trade found"
            }

        # Calculate basic trade metrics
        buy_price = last_buy_trade.get('price', 0)
        if buy_price <= 0:
            return SellDecision.BLOCK, [SellReason.LOSS_PREVENTION], {
                "message": "Invalid buy price"
            }

        profit_percentage = ((current_price - buy_price) / buy_price) * 100
        additional_data['profit_percentage'] = profit_percentage
        additional_data['buy_price'] = buy_price
        additional_data['current_price'] = current_price

        # 1. Loss Prevention Check (Highest Priority)
        loss_check = await self._check_loss_prevention(
            profit_percentage, last_buy_trade, additional_data
        )
        if loss_check[0] != SellDecision.HOLD:
            return loss_check

        # 2. Profit Analysis
        profit_decision, profit_reasons = await self._analyze_profit_conditions(
            profit_percentage, signal_data, additional_data
        )
        reasons.extend(profit_reasons)

        # 3. Time-based Analysis
        time_decision, time_reasons = await self._analyze_time_factors(
            last_buy_trade, additional_data
        )
        reasons.extend(time_reasons)

        # 4. Market Conditions Analysis
        market_decision, market_reasons = await self._analyze_market_conditions(
            current_price, market_data, additional_data
        )
        reasons.extend(market_reasons)

        # 5. Risk Management Analysis
        risk_decision, risk_reasons = await self._analyze_risk_factors(
            profit_percentage, portfolio_data, additional_data
        )
        reasons.extend(risk_reasons)

        # 6. Signal Confidence Analysis
        confidence_decision, confidence_reasons = await self._analyze_signal_confidence(
            signal_data, profit_percentage, additional_data
        )
        reasons.extend(confidence_reasons)

        # Combine all decisions
        final_decision = self._combine_decisions([
            profit_decision, time_decision, market_decision,
            risk_decision, confidence_decision
        ])

        return final_decision, reasons, additional_data

    async def _check_loss_prevention(
            self,
            profit_percentage: float,
            last_buy_trade: Dict[str, Any],
            additional_data: Dict[str, Any]
    ) -> Tuple[SellDecision, List[SellReason], Dict[str, Any]]:
        """Check for loss prevention conditions."""

        # Prevent sales at a loss (current behavior)
        if profit_percentage <= 0:
            return SellDecision.BLOCK, [SellReason.LOSS_PREVENTION], {
                "message": f"Would result in {profit_percentage:.2f}% loss",
                "recommendation": "Wait for profitable exit or implement stop-loss"
            }

        # Check if loss exceeds maximum threshold
        if profit_percentage < -self.config['max_loss_percentage']:
            return SellDecision.SELL, [SellReason.STOP_LOSS], {
                "message": f"Stop-loss triggered at {profit_percentage:.2f}% loss"
            }

        return SellDecision.HOLD, [], {}

    async def _analyze_profit_conditions(
            self,
            profit_percentage: float,
            signal_data: Dict[str, Any],
            additional_data: Dict[str, Any]
    ) -> Tuple[SellDecision, List[SellReason]]:
        """Analyze profit-related conditions."""
        reasons = []

        # Check minimum profit threshold
        if profit_percentage < self.config['min_profit_percentage']:
            reasons.append(SellReason.INSUFFICIENT_PROFIT)
            return SellDecision.HOLD, reasons

        # Check take profit targets
        take_profit_targets = signal_data.get('take_profit_targets', [])
        if take_profit_targets:
            buy_price = additional_data.get('buy_price', 0)
            current_price = additional_data.get('current_price', 0)

            for i, target in enumerate(take_profit_targets):
                if current_price >= target:
                    reasons.append(SellReason.PROFIT_TARGET)
                    additional_data['profit_target_hit'] = i + 1

                    # Decide on full or partial sell based on target
                    if i < len(take_profit_targets) - 1:
                        return SellDecision.PARTIAL_SELL, reasons
                    else:
                        return SellDecision.SELL, reasons

        # Good profit, but no specific target hit
        if profit_percentage > self.config['min_profit_percentage'] * 2:
            reasons.append(SellReason.PROFIT_TARGET)
            return SellDecision.SELL, reasons

        return SellDecision.HOLD, reasons

    async def _analyze_time_factors(
            self,
            last_buy_trade: Dict[str, Any],
            additional_data: Dict[str, Any]
    ) -> Tuple[SellDecision, List[SellReason]]:
        """Analyze time-based factors."""
        reasons = []

        try:
            trade_timestamp = last_buy_trade.get('timestamp')
            if not trade_timestamp:
                return SellDecision.HOLD, reasons

            # Parse timestamp
            if isinstance(trade_timestamp, str):
                trade_time = datetime.fromisoformat(trade_timestamp.replace('Z', '+00:00'))
            else:
                trade_time = trade_timestamp

            time_held = datetime.now() - trade_time.replace(tzinfo=None)
            additional_data['time_held_minutes'] = time_held.total_seconds() / 60

            # Check minimum hold time
            if time_held < timedelta(minutes=self.config['min_hold_minutes']):
                reasons.append(SellReason.TIME_BASED)
                return SellDecision.HOLD, reasons

            # Check maximum hold time
            if time_held > timedelta(hours=self.config['max_hold_hours']):
                reasons.append(SellReason.TIME_BASED)
                return SellDecision.SELL, reasons

        except Exception as e:
            additional_data['time_analysis_error'] = str(e)

        return SellDecision.HOLD, reasons

    async def _analyze_market_conditions(
            self,
            current_price: float,
            market_data: Optional[Dict[str, Any]],
            additional_data: Dict[str, Any]
    ) -> Tuple[SellDecision, List[SellReason]]:
        """Analyze market conditions."""
        reasons = []

        if not market_data:
            return SellDecision.HOLD, reasons

        # Check volatility
        volatility = market_data.get('volatility_24h', 0)
        if volatility > self.config['volatility_threshold']:
            reasons.append(SellReason.VOLATILITY)
            additional_data['volatility'] = volatility
            # High volatility suggests caution, but not necessarily sell

        # Check volume
        volume_change = market_data.get('volume_change_24h', 0)
        if volume_change < -self.config['volume_drop_threshold']:
            reasons.append(SellReason.MARKET_CONDITIONS)
            additional_data['volume_change'] = volume_change

        # Market trend analysis
        trend = market_data.get('trend', 'neutral')
        if trend == 'bearish':
            reasons.append(SellReason.MARKET_CONDITIONS)
            return SellDecision.SELL, reasons

        return SellDecision.HOLD, reasons

    async def _analyze_risk_factors(
            self,
            profit_percentage: float,
            portfolio_data: Optional[Dict[str, Any]],
            additional_data: Dict[str, Any]
    ) -> Tuple[SellDecision, List[SellReason]]:
        """Analyze risk management factors."""
        reasons = []

        if not portfolio_data:
            return SellDecision.HOLD, reasons

        # Check portfolio drawdown
        portfolio_pnl = portfolio_data.get('total_pnl_percentage', 0)
        if portfolio_pnl < -self.config['max_drawdown_percentage']:
            reasons.append(SellReason.RISK_MANAGEMENT)
            additional_data['portfolio_drawdown'] = portfolio_pnl
            return SellDecision.SELL, reasons

        # Check position concentration
        position_size_percentage = portfolio_data.get('position_size_percentage', 0)
        if position_size_percentage > 20:  # More than 20% of portfolio
            reasons.append(SellReason.RISK_MANAGEMENT)
            additional_data['position_concentration'] = position_size_percentage
            # Suggest partial sell for large positions
            return SellDecision.PARTIAL_SELL, reasons

        return SellDecision.HOLD, reasons

    async def _analyze_signal_confidence(
            self,
            signal_data: Dict[str, Any],
            profit_percentage: float,
            additional_data: Dict[str, Any]
    ) -> Tuple[SellDecision, List[SellReason]]:
        """Analyze signal confidence factors."""
        reasons = []

        confidence = signal_data.get('confidence', 0)
        additional_data['signal_confidence'] = confidence

        # Adjust confidence requirement based on profit
        required_confidence = self.config['min_sell_confidence']
        if profit_percentage < self.config['confidence_boost_profit']:
            required_confidence += 10  # Require higher confidence for low-profit sells

        if confidence < required_confidence:
            reasons.append(SellReason.SIGNAL_CONFIDENCE)
            additional_data['confidence_required'] = required_confidence
            return SellDecision.HOLD, reasons

        return SellDecision.SELL, reasons

    def _combine_decisions(self, decisions: List[SellDecision]) -> SellDecision:
        """Combine multiple decision factors into final decision."""
        # Priority order: BLOCK > SELL > PARTIAL_SELL > HOLD

        if SellDecision.BLOCK in decisions:
            return SellDecision.BLOCK

        sell_count = decisions.count(SellDecision.SELL)
        partial_sell_count = decisions.count(SellDecision.PARTIAL_SELL)

        # If majority suggests selling
        if sell_count >= 2:
            return SellDecision.SELL

        # If any suggest partial sell and others don't block
        if partial_sell_count >= 1 and SellDecision.BLOCK not in decisions:
            return SellDecision.PARTIAL_SELL

        # Default to hold
        return SellDecision.HOLD

    async def get_sell_volume(
            self,
            decision: SellDecision,
            available_volume: float,
            additional_data: Dict[str, Any]
    ) -> float:
        """Calculate the volume to sell based on decision."""

        if decision == SellDecision.BLOCK:
            return 0.0

        if decision == SellDecision.SELL:
            return available_volume

        if decision == SellDecision.PARTIAL_SELL:
            # Sell percentage based on profit target hit or risk factors
            profit_target_hit = additional_data.get('profit_target_hit', 1)

            # Sell more for higher profit targets
            sell_percentages = [0.25, 0.5, 0.75, 1.0]  # 25%, 50%, 75%, 100%

            if profit_target_hit <= len(sell_percentages):
                sell_percentage = sell_percentages[profit_target_hit - 1]
            else:
                sell_percentage = 1.0

            return available_volume * sell_percentage

        return 0.0

    def get_decision_summary(
            self,
            decision: SellDecision,
            reasons: List[SellReason],
            additional_data: Dict[str, Any]
    ) -> str:
        """Generate a human-readable summary of the sell decision."""

        profit_pct = additional_data.get('profit_percentage', 0)

        if decision == SellDecision.BLOCK:
            return f"❌ SELL BLOCKED: {additional_data.get('message', 'Unknown reason')}"

        if decision == SellDecision.SELL:
            reason_text = ", ".join([reason.value for reason in reasons[:2]])
            return f"✅ SELL APPROVED: {reason_text} (Profit: {profit_pct:+.2f}%)"

        if decision == SellDecision.PARTIAL_SELL:
            reason_text = ", ".join([reason.value for reason in reasons[:2]])
            return f"⚡ PARTIAL SELL: {reason_text} (Profit: {profit_pct:+.2f}%)"

        if decision == SellDecision.HOLD:
            if reasons:
                reason_text = ", ".join([reason.value for reason in reasons[:2]])
                return f"⏳ HOLD: {reason_text} (Profit: {profit_pct:+.2f}%)"
            else:
                return f"⏳ HOLD: Waiting for better conditions (Profit: {profit_pct:+.2f}%)"

        return f"❓ UNKNOWN DECISION: {decision.value}"


# Example usage (for future integration):
"""
# This is how the SellDecisionManager would be used in the trading system:

async def example_usage():
    from src.sell_decision_manager import SellDecisionManager, SellDecision

    # Initialize the manager
    sell_manager = SellDecisionManager(settings)

    # Example signal data
    signal_data = {
        'action': 'SELL',
        'base_currency': 'BTC',
        'confidence': 85,
        'take_profit_targets': [45000, 47000, 50000]
    }

    # Example last buy trade
    last_buy_trade = {
        'price': 43000.0,
        'volume': 0.1,
        'timestamp': '2024-01-15 10:30:00'
    }

    # Current market price
    current_price = 45500.0

    # Get sell decision
    decision, reasons, additional_data = await sell_manager.should_sell(
        signal_data=signal_data,
        last_buy_trade=last_buy_trade,
        current_price=current_price
    )

    if decision != SellDecision.BLOCK:
        # Calculate sell volume
        available_volume = last_buy_trade['volume']
        sell_volume = await sell_manager.get_sell_volume(
            decision, available_volume, additional_data
        )

        # Get summary
        summary = sell_manager.get_decision_summary(decision, reasons, additional_data)
        print(summary)

        # Execute the sell if approved
        if sell_volume > 0:
            # Place sell order with calculated volume
            pass
    else:
        print(sell_manager.get_decision_summary(decision, reasons, additional_data))
"""