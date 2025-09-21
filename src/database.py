"""Enhanced database with channel-specific wallet support."""
import sqlite3
from typing import Dict, Any, List, Optional
import json
from config.settings import BASE_DIR, settings


class TradingDatabase:
    """Enhanced database with channel-specific wallet management."""
    def __init__(self, db_name: str = None):
        if not db_name:
            db_name = f"{'dry_run' if settings.DRY_RUN else 'live_trading'}.db"

        self.db_path = BASE_DIR / db_name
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Create the necessary tables with channel-specific wallet support."""
        # Original trades table (no changes needed)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                base_currency TEXT NOT NULL,
                quote_currency TEXT NOT NULL,
                telegram_channel TEXT,
                side TEXT NOT NULL,
                volume REAL NOT NULL,
                price REAL,
                ordertype TEXT NOT NULL,
                status TEXT NOT NULL,
                take_profit REAL,
                stop_loss REAL,
                take_profit_target INTEGER,
                leverage INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Enhanced wallet table with channel support
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                currency TEXT NOT NULL,
                balance REAL NOT NULL,
                telegram_channel TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(currency, telegram_channel)
            )
        """)

        # Channel configurations table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS channel_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT UNIQUE NOT NULL,
                start_currency TEXT NOT NULL DEFAULT 'USDT',
                start_amount REAL NOT NULL DEFAULT 1000.0,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # LLM responses table (no changes needed)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT,
                action TEXT,
                base_currency TEXT,
                quote_currency TEXT,
                confidence INTEGER,
                entry_price_range TEXT,
                leverage TEXT,
                stop_loss REAL,
                take_profit_targets TEXT,
                take_profit_target INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # MODIFIED: Wallet history table with full balance snapshot
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                channel_name TEXT NOT NULL,
                total_value_usd REAL NOT NULL,
                balances_json TEXT
            )
        """)
        self.conn.commit()

    def reset_tables(self):
        """
        Clear all data from tables for a fresh dry-run session.
        CRITICAL: This will only execute if DRY_RUN is enabled in settings.
        """
        if not settings.DRY_RUN:
            print("❌ FATAL: reset_tables() called in LIVE mode. Aborting operation for safety.")
            return

        print("Resetting database for a new dry-run session...")
        self.cursor.execute("DELETE FROM trades")
        self.cursor.execute("DELETE FROM wallet")
        self.cursor.execute("DELETE FROM llm_responses")
        self.cursor.execute("DELETE FROM wallet_history")
        # Note: channel_configs are preserved across sessions.
        self.conn.commit()

    def add_wallet_history_record(self, channel_name: str, total_value_usd: float, balances: Dict[str, float]):
        """Adds a new wallet balance snapshot to the history table."""
        try:
            balances_str = json.dumps(balances)
            self.cursor.execute("""
                INSERT INTO wallet_history (channel_name, total_value_usd, balances_json)
                VALUES (?, ?, ?)
            """, (channel_name, total_value_usd, balances_str))
            self.conn.commit()
        except Exception as e:
            print(f"❌ Error adding wallet history record: {e}")
            self.conn.rollback()

    def get_historical_assets_summary(self, channel_name: str) -> Dict[str, float]:
        """
        Gets a summary of all assets ever held by a channel, returning the max balance recorded for each.
        This is used to build a historical asset allocation pie chart.
        """
        self.cursor.execute("SELECT balances_json FROM wallet_history WHERE channel_name = ?", (channel_name,))
        rows = self.cursor.fetchall()

        max_balances: Dict[str, float] = {}

        for row in rows:
            if row and row[0]:  # Check if row and balances_json are not None
                try:
                    balances = json.loads(row[0])
                    for currency, balance in balances.items():
                        # Track the peak balance for each currency
                        if balance > max_balances.get(currency, 0):
                            max_balances[currency] = balance
                except (json.JSONDecodeError, TypeError):
                    continue  # Skip malformed or empty data

        # Also include current balances in case there's no history yet
        current_balances = self.get_channel_balance(channel_name)
        for currency, balance in current_balances.items():
            if balance > max_balances.get(currency, 0):
                max_balances[currency] = balance

        return max_balances

    def get_wallet_history_for_channel(self, channel_name: str) -> List[Dict[str, Any]]:
        """Gets the full, ordered wallet history for a given channel."""
        self.cursor.execute("""
            SELECT timestamp, balances_json 
            FROM wallet_history 
            WHERE channel_name = ? 
            ORDER BY timestamp ASC
        """, (channel_name,))

        history = []
        for row in self.cursor.fetchall():
            try:
                history.append({
                    "timestamp": row[0],
                    "balances": json.loads(row[1])
                })
            except (json.JSONDecodeError, TypeError):
                continue # Skip malformed records
        return history

    def initialize_channel_wallet(self, channel: str, currency: str = "USDT", amount: float = 1000.0):
        """Initialize a channel's wallet with starting balance."""
        try:
            # Add or update channel config
            self.cursor.execute("""
                INSERT OR REPLACE INTO channel_configs 
                (channel_name, start_currency, start_amount, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (channel, currency, amount))

            # Add starting balance to wallet
            self.cursor.execute("""
                INSERT OR REPLACE INTO wallet 
                (currency, balance, telegram_channel, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (currency, amount, channel))

            self.conn.commit()
            print(f"✅ Initialized {channel} wallet with {amount} {currency}")

        except Exception as e:
            print(f"❌ Error initializing channel wallet: {e}")
            self.conn.rollback()

    def get_channel_balance(self, channel: str, currency: str = None) -> Dict[str, float]:
        """Get balance for a specific channel."""
        if currency:
            self.cursor.execute("""
                SELECT balance FROM wallet 
                WHERE telegram_channel = ? AND currency = ?
            """, (channel, currency))
            result = self.cursor.fetchone()
            return {currency: result[0] if result else 0.0}
        else:
            self.cursor.execute("""
                SELECT currency, balance FROM wallet 
                WHERE telegram_channel = ?
            """, (channel,))
            return {row[0]: row[1] for row in self.cursor.fetchall()}

    def update_channel_balance(self, channel: str, currency: str, new_balance: float):
        """Update balance for a specific channel and currency."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO wallet 
            (currency, balance, telegram_channel, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """, (currency, new_balance, channel))
        self.conn.commit()

    def get_all_channel_balances(self) -> List[Dict[str, Any]]:
        """Get all balances organized by channel."""
        self.cursor.execute("""
            SELECT w.currency, w.balance, w.telegram_channel, 
                   cc.start_amount, cc.start_currency
            FROM wallet w
            LEFT JOIN channel_configs cc ON w.telegram_channel = cc.channel_name
            ORDER BY w.telegram_channel, w.currency
        """)

        results = []
        for row in self.cursor.fetchall():
            results.append({
                'currency': row[0],
                'balance': row[1],
                'channel': row[2] or 'global',
                'start_amount': row[3],
                'start_currency': row[4]
            })
        return results

    def get_channel_configs(self) -> List[Dict[str, Any]]:
        """Get all channel configurations."""
        self.cursor.execute("""
            SELECT channel_name, start_currency, start_amount, is_active, created_at
            FROM channel_configs
            ORDER BY channel_name
        """)

        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def sync_wallet(self, balances: Dict[str, float], channel: str = None):
        """
        Sync wallet balances. If channel is specified, only sync that channel's balance.
        Otherwise, sync global balances.
        """
        if channel:
            # Channel-specific sync - clear and update only this channel
            self.cursor.execute("DELETE FROM wallet WHERE telegram_channel = ?", (channel,))
            for currency, balance in balances.items():
                self.cursor.execute("""
                    INSERT INTO wallet (currency, balance, telegram_channel) 
                    VALUES (?, ?, ?)
                """, (currency, balance, channel))
        else:
            # Global sync - clear and update global balances (channel is NULL)
            self.cursor.execute("DELETE FROM wallet WHERE telegram_channel IS NULL")
            for currency, balance in balances.items():
                self.cursor.execute("""
                    INSERT INTO wallet (currency, balance, telegram_channel) 
                    VALUES (?, ?, NULL)
                """, (currency, balance))

        self.conn.commit()
        print(f"Wallet synced with {len(balances)} assets for {channel or 'global'}")

    def get_balance(self) -> Dict[str, float]:
        """Get global balance (for backwards compatibility)."""
        self.cursor.execute("""
            SELECT currency, balance FROM wallet 
            WHERE telegram_channel IS NULL
        """)
        return {row[0]: row[1] for row in self.cursor.fetchall()}
    
    def update_balance(self, currency: str, new_balance: float):
        """Update global balance for backwards compatibility."""
        self.cursor.execute("""
            INSERT OR REPLACE INTO wallet (currency, balance, telegram_channel) 
            VALUES (?, ?, NULL)
        """, (currency, new_balance))
        self.conn.commit()

    def add_trade(self, trade_data: Dict[str, Any]) -> int:
        """Add a new trade to the database."""
        self.cursor.execute("""
            INSERT INTO trades (base_currency, quote_currency, telegram_channel, side, volume, price, ordertype, status, take_profit, stop_loss, take_profit_target, leverage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_data["base_currency"],
            trade_data["quote_currency"],
            trade_data.get("telegram_channel"),
            trade_data["side"],
            trade_data["volume"],
            trade_data.get("price"),
            trade_data["ordertype"],
            trade_data["status"],
            trade_data.get("take_profit"),
            trade_data.get("stop_loss"),
            trade_data.get("take_profit_target"),
            trade_data.get("leverage", 0)
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_last_buy_trade(self, telegram_channel: str, base_currency: str, quote_currency: str) -> Optional[Dict[str, Any]]:
        """Get the most recent BUY trade for a specific channel and pair."""
        self.cursor.execute("""
            SELECT * FROM trades 
            WHERE telegram_channel = ? 
            AND base_currency = ? 
            AND quote_currency = ? 
            AND LOWER(side) = 'buy'
            ORDER BY timestamp DESC 
            LIMIT 1
        """, (telegram_channel, base_currency, quote_currency))

        row = self.cursor.fetchone()
        if not row:
            return None

        columns = [description[0] for description in self.cursor.description]
        return dict(zip(columns, row))

    def add_llm_response(self, response_data: Dict[str, Any], channel: str = None):
        """Add a new LLM response to the database with channel information."""
        self.cursor.execute("""
            INSERT INTO llm_responses (channel, action, base_currency, quote_currency, confidence, 
                                     entry_price_range, leverage, stop_loss, take_profit_targets)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            channel,
            response_data.get('action'),
            response_data.get('base_currency'),
            response_data.get('quote_currency'),
            response_data.get('confidence'),
            json.dumps(response_data.get('entry_price_range')),
            str(response_data.get('leverage')),
            response_data.get('stop_loss'),
            json.dumps(response_data.get('take_profit_targets'))
        ))
        self.conn.commit()

    def get_trades(self) -> List[Dict[str, Any]]:
        """Retrieve all trades from the database."""
        self.cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def close(self):
        """Close the database connection."""
        self.conn.close()