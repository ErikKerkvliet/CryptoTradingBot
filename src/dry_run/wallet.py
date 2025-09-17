"""Enhanced virtual wallet with channel-specific balance management."""
from typing import Dict, Any
from .database import DryRunDatabase


class VirtualWallet:
    def __init__(self, db: DryRunDatabase, default_balances: Dict[str, float] = None,
                 channel_configs: Dict[str, Dict[str, float]] = None):
        """
        Initialize the wallet with global and channel-specific configurations.

        Args:
            db: The database instance
            default_balances: Default global balances (for backwards compatibility)
            channel_configs: Dictionary of channel configurations
                            Format: {"channel_name": {"currency": amount}}
        """
        self.db = db
        if default_balances is None:
            self.default_balances = {"USDT": 1000.0}
        else:
            self.default_balances = default_balances

        self.channel_configs = channel_configs or {}

    def reset(self):
        """
        Reset the wallet to its default state.
        This initializes both global balances and channel-specific balances.
        """
        # Clear all existing data
        self.db.reset_tables()

        # Initialize global balances (for backwards compatibility)
        print(f"Populating global wallet with default balances: {self.default_balances}")
        for currency, balance in self.default_balances.items():
            self.db.update_balance(currency, balance)

        # Initialize channel-specific wallets
        if self.channel_configs:
            for channel, config in self.channel_configs.items():
                for currency, amount in config.items():
                    self.db.initialize_channel_wallet(channel, currency, amount)
        else:
            # Initialize some common test channels if no config provided
            default_channels = [
                "testchannel",
                "mycryptobottestchannel",
                "universalcryptosignalss"
            ]

            for channel in default_channels:
                self.db.initialize_channel_wallet(channel, "USDT", 1000.0)

    def get_balance(self) -> Dict[str, float]:
        """Get global balance (for backwards compatibility)."""
        return self.db.get_balance()

    def get_channel_balance(self, channel: str) -> Dict[str, float]:
        """Get balance for a specific channel."""
        return self.db.get_channel_balance(channel)

    def update_balance(self, currency: str, new_balance: float):
        """Update global balance (for backwards compatibility)."""
        self.db.update_balance(currency, new_balance)

    def update_channel_balance(self, channel: str, currency: str, new_balance: float):
        """Update balance for a specific channel and currency."""
        self.db.update_channel_balance(channel, currency, new_balance)

    def get_all_balances(self) -> Dict[str, Dict[str, float]]:
        """
        Get all balances organized by channel.
        Returns: {"global": {...}, "channel1": {...}, "channel2": {...}}
        """
        all_balances = {"global": self.get_balance()}

        # Get all unique channels from the database
        self.db.cursor.execute("SELECT DISTINCT telegram_channel FROM wallet WHERE telegram_channel IS NOT NULL")
        channels = [row[0] for row in self.db.cursor.fetchall()]

        for channel in channels:
            all_balances[channel] = self.get_channel_balance(channel)

        return all_balances

    def initialize_channel_if_needed(self, channel: str, currency: str = "USDT", amount: float = 1000.0):
        """Initialize a channel wallet if it doesn't exist."""
        existing_balance = self.get_channel_balance(channel)
        if not existing_balance:
            print(f"🔄 Auto-initializing wallet for new channel: {channel}")
            self.db.initialize_channel_wallet(channel, currency, amount)
            return True
        return False

    def transfer_between_channels(self, from_channel: str, to_channel: str,
                                  currency: str, amount: float) -> bool:
        """
        Transfer funds between channels (for admin use).
        Returns True if successful, False otherwise.
        """
        try:
            from_balance = self.get_channel_balance(from_channel).get(currency, 0)

            if from_balance < amount:
                print(f"❌ Insufficient {currency} in {from_channel}: {from_balance} < {amount}")
                return False

            to_balance = self.get_channel_balance(to_channel).get(currency, 0)

            # Update balances
            self.update_channel_balance(from_channel, currency, from_balance - amount)
            self.update_channel_balance(to_channel, currency, to_balance + amount)

            print(f"✅ Transferred {amount} {currency} from {from_channel} to {to_channel}")
            return True

        except Exception as e:
            print(f"❌ Transfer failed: {e}")
            return False

    def get_channel_performance(self, channel: str) -> Dict[str, Any]:
        """
        Calculate performance metrics for a channel.
        Returns profit/loss, win rate, etc.
        """
        try:
            # Get channel config to find starting amount
            configs = self.db.get_channel_configs()
            start_amount = 1000.0  # default
            start_currency = "USDT"  # default

            for config in configs:
                if config['channel_name'] == channel:
                    start_amount = config['start_amount']
                    start_currency = config['start_currency']
                    break

            # Get current balance
            current_balances = self.get_channel_balance(channel)
            current_amount = current_balances.get(start_currency, 0)

            # Calculate basic metrics
            profit_loss = current_amount - start_amount
            profit_loss_pct = (profit_loss / start_amount) * 100 if start_amount > 0 else 0

            # Get trade statistics for this channel
            self.db.cursor.execute("""
                SELECT COUNT(*) as total_trades,
                       SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) as buy_trades,
                       SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) as sell_trades
                FROM trades 
                WHERE telegram_channel = ?
            """, (channel,))

            trade_stats = self.db.cursor.fetchone()
            total_trades = trade_stats[0] if trade_stats else 0
            buy_trades = trade_stats[1] if trade_stats else 0
            sell_trades = trade_stats[2] if trade_stats else 0

            return {
                'channel': channel,
                'start_amount': start_amount,
                'start_currency': start_currency,
                'current_amount': current_amount,
                'profit_loss': profit_loss,
                'profit_loss_pct': profit_loss_pct,
                'total_trades': total_trades,
                'buy_trades': buy_trades,
                'sell_trades': sell_trades,
                'is_profitable': profit_loss > 0
            }

        except Exception as e:
            print(f"❌ Error calculating performance for {channel}: {e}")
            return {
                'channel': channel,
                'error': str(e)
            }