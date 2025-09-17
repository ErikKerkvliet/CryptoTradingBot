"""Manages the SQLite database for dry-run trading."""
import sqlite3
from typing import Dict, Any, List, Optional
import json
from config.settings import BASE_DIR  # Import the base directory path


class DryRunDatabase:
    def __init__(self, db_name: str = "dry_run.db"):
        # Use an absolute path to ensure the database is always in the project root
        self.db_path = BASE_DIR / db_name
        self.conn = sqlite3.connect(self.db_path)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Create the necessary tables if they don't exist."""
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
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                currency TEXT PRIMARY KEY,
                balance REAL NOT NULL
            )
        """)
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
        self.conn.commit()

    def reset_tables(self):
        """
        Clears all data from the tables for a fresh start.
        """
        print("Resetting dry-run database for a new session...")
        self.cursor.execute("DELETE FROM trades")
        self.cursor.execute("DELETE FROM wallet")
        #self.cursor.execute("DELETE FROM llm_responses")
        self.conn.commit()

    def get_balance(self) -> Dict[str, float]:
        """Get the current balance of all currencies in the wallet."""
        self.cursor.execute("SELECT currency, balance FROM wallet")
        return {row[0]: row[1] for row in self.cursor.fetchall()}

    def update_balance(self, currency: str, new_balance: float):
        """Update the balance of a specific currency."""
        self.cursor.execute("""
            INSERT INTO wallet (currency, balance) VALUES (?, ?)
            ON CONFLICT(currency) DO UPDATE SET balance = excluded.balance
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
        """
        Retrieves the most recent BUY trade for a specific trading pair from a specific Telegram channel.

        Args:
            telegram_channel: The name/ID of the Telegram channel
            base_currency: The base currency (e.g., 'BTC')
            quote_currency: The quote currency (e.g., 'USDT')

        Returns:
            Dictionary containing trade data if found, None otherwise
        """
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

    def get_open_position_volume(self, telegram_channel: str, base_currency: str, quote_currency: str) -> float:
        """
        Calculates the net open position volume for a specific pair from a specific channel.
        This considers all BUY and SELL trades to determine the current position size.

        Args:
            telegram_channel: The name/ID of the Telegram channel
            base_currency: The base currency (e.g., 'BTC')
            quote_currency: The quote currency (e.g., 'USDT')

        Returns:
            Net volume (positive = long position, negative = short position, 0 = flat)
        """
        self.cursor.execute("""
            SELECT side, SUM(volume) as total_volume
            FROM trades 
            WHERE telegram_channel = ? 
            AND base_currency = ? 
            AND quote_currency = ?
            GROUP BY LOWER(side)
        """, (telegram_channel, base_currency, quote_currency))

        rows = self.cursor.fetchall()
        buy_volume = 0.0
        sell_volume = 0.0

        for side, volume in rows:
            if side.lower() == 'buy':
                buy_volume += volume
            elif side.lower() == 'sell':
                sell_volume += volume

        return buy_volume - sell_volume

    def get_trades_by_channel(self, telegram_channel: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieves all trades from a specific Telegram channel, ordered by most recent first.

        Args:
            telegram_channel: The name/ID of the Telegram channel
            limit: Optional limit on number of trades to return

        Returns:
            List of trade dictionaries
        """
        query = """
            SELECT * FROM trades 
            WHERE telegram_channel = ? 
            ORDER BY timestamp DESC
        """
        params = [telegram_channel]

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        self.cursor.execute(query, params)
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def add_llm_response(self, response_data: Dict[str, Any], channel: str = None):
        """Adds a new LLM response to the database with channel information."""
        self.cursor.execute("""
            INSERT INTO llm_responses (channel, action, base_currency, quote_currency, confidence, 
                                     entry_price_range, leverage, stop_loss, take_profit_targets)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            channel,  # Add channel as first parameter
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

    def _transform_llm_response(self, row: tuple, columns: list) -> Optional[Dict[str, Any]]:
        """Transforms a raw DB row into a formatted dictionary with correct data types."""
        if not row:
            return None

        response = dict(zip(columns, row))

        for field in ['entry_price_range', 'take_profit_targets']:
            if response.get(field):
                try:
                    response[field] = json.loads(response[field])
                except (json.JSONDecodeError, TypeError):
                    response[field] = None
            else:
                response[field] = None

        if response.get('confidence') is not None:
            response['confidence'] = int(response['confidence'])
        if response.get('stop_loss') is not None:
            response['stop_loss'] = float(response['stop_loss'])

        return response

    def get_llm_responses_by_channel(self, channel: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieves LLM responses from a specific channel.

        Args:
            channel: The name/ID of the channel
            limit: Optional limit on number of responses to return

        Returns:
            List of LLM response dictionaries
        """
        query = """
            SELECT * FROM llm_responses 
            WHERE channel = ? 
            ORDER BY timestamp DESC
        """
        params = [channel]

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        self.cursor.execute(query, params)
        columns = [description[0] for description in self.cursor.description]

        results = []
        for row in self.cursor.fetchall():
            result = self._transform_llm_response(row, columns)
            if result:
                results.append(result)

        return results

    def get_llm_responses(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Retrieve all LLM responses from the database."""
        query = "SELECT * FROM llm_responses ORDER BY timestamp DESC"
        if limit:
            query += f" LIMIT {limit}"

        self.cursor.execute(query)
        columns = [description[0] for description in self.cursor.description]

        results = []
        for row in self.cursor.fetchall():
            result = self._transform_llm_response(row, columns)
            if result:
                results.append(result)

        return results

    def get_trades(self) -> List[Dict[str, Any]]:
        """Retrieve all trades from the database."""
        self.cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC")
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def close(self):
        """Close the database connection."""
        self.conn.close()