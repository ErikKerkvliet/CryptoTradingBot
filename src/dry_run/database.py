# src/dry_run/database.py

"""Manages the SQLite database for dry-run trading."""
import sqlite3
from typing import Dict, Any, List

class DryRunDatabase:
    def __init__(self, db_name: str = "dry_run.db"):
        self.db_name = db_name
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()
        self._create_tables()

    def _create_tables(self):
        """Create the necessary tables if they don't exist."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
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

    def reset_tables(self):
        """
        Clears all data from the trades and wallet tables for a fresh start.
        """
        print("Resetting dry-run database for a new session...")
        self.cursor.execute("DELETE FROM trades")
        self.cursor.execute("DELETE FROM wallet")
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
            INSERT INTO trades (pair, side, volume, price, ordertype, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            trade_data["pair"],
            trade_data["side"],
            trade_data["volume"],
            trade_data.get("price"),
            trade_data["ordertype"],
            "simulated"
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