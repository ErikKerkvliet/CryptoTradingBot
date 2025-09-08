"""Manages the SQLite database for live trading."""
import sqlite3
from typing import Dict, Any, List

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
                status TEXT NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet (
                currency TEXT PRIMARY KEY,
                balance REAL NOT NULL
            )
        """)
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
            INSERT INTO trades (base_currency, quote_currency, telegram_channel, side, volume, price, ordertype, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_data["base_currency"],
            trade_data["quote_currency"],
            trade_data.get("telegram_channel"),
            trade_data["side"],
            trade_data["volume"],
            trade_data.get("price"),
            trade_data["ordertype"],
            trade_data["status"]
        ))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_trades(self) -> List[Dict[str, Any]]:
        """Retrieve all trades from the database."""
        self.cursor.execute("SELECT * FROM trades")
        columns = [description[0] for description in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def close(self):
        """Close the database connection."""
        self.conn.close()