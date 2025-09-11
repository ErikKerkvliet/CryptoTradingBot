"""Manages the SQLite database for live trading."""
import sqlite3
from typing import Dict, Any, List, Optional
import json


class TradingDatabase:
    """Manages the database for storing live trades and wallet balances."""
    def __init__(self, db_name: str = "live_trading.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(self.db_name)
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
                take_profit_level INTEGER,
                leverage INTEGER DEFAULT 0
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                currency TEXT PRIMARY KEY,
                balance REAL NOT NULL
            )
        """)
        # self.cursor.execute("""
        #     CREATE TABLE IF NOT EXISTS llm_responses (
        #         id INTEGER PRIMARY KEY AUTOINCREMENT,
        #         action TEXT,
        #         base_currency TEXT,
        #         quote_currency TEXT,
        #         confidence INTEGER,
        #         entry_price_range TEXT,
        #         leverage TEXT,
        #         stop_loss REAL,
        #         take_profit_levels TEXT,
        #         timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        #     )
        # """)
        self.conn.commit()

    def sync_wallet(self, balances: Dict[str, float]):
        """
        Clears the wallet table and inserts the latest balances from the exchange.
        """
        self.cursor.execute("DELETE FROM wallet")
        for currency, balance in balances.items():
            self.cursor.execute("""
                INSERT INTO wallet (currency, balance) VALUES (?, ?)
            """, (currency, balance))
        self.conn.commit()
        print(f"Wallet synced with {len(balances)} assets.")

    def add_trade(self, trade_data: Dict[str, Any]) -> int:
        """Add a new trade to the database."""
        self.cursor.execute("""
            INSERT INTO trades (base_currency, quote_currency, telegram_channel, side, volume, price, ordertype, status, take_profit, stop_loss, take_profit_lever)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            trade_data.get("take_profit_lever")
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def add_llm_response(self, response_data: Dict[str, Any]):
        """Adds a new LLM response to the database."""
        self.cursor.execute("""
            INSERT INTO llm_responses (action, base_currency, quote_currency, confidence, 
                                     entry_price_range, leverage, stop_loss, take_profit_levels)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            response_data.get('action'),
            response_data.get('base_currency'),
            response_data.get('quote_currency'),
            response_data.get('confidence'),
            json.dumps(response_data.get('entry_price_range')),
            str(response_data.get('leverage')),
            response_data.get('stop_loss'),
            json.dumps(response_data.get('take_profit_levels'))
        ))
        self.conn.commit()

    def _transform_llm_response(self, row: tuple, columns: list) -> Optional[Dict[str, Any]]:
        """Transforms a raw DB row into a formatted dictionary with correct data types."""
        if not row:
            return None

        response = dict(zip(columns, row))

        for field in ['entry_price_range', 'take_profit_levels']:
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

    def get_llm_response(self, response_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific LLM response, or the latest one.
        """
        if response_id is None:
            self.cursor.execute("SELECT * FROM llm_responses ORDER BY id DESC LIMIT 1")
        else:
            self.cursor.execute("SELECT * FROM llm_responses WHERE id = ?", (response_id,))

        row = self.cursor.fetchone()
        if not row:
            return None

        columns = [description[0] for description in self.cursor.description]
        return self._transform_llm_response(row, columns)

    def get_trades(self) -> List[Dict[str, Any]]:
        """Retrieve all trades from the database."""
        self.cursor.execute("SELECT * FROM trades")
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def close(self):
        """Close the database connection."""
        self.conn.close()