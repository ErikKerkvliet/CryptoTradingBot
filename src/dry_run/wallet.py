# src/dry_run/wallet.py

"""Manages the virtual wallet for dry-run trading."""
from typing import Dict
from .database import DryRunDatabase


class VirtualWallet:
    def __init__(self, db: DryRunDatabase, default_balances: Dict[str, float] = None):
        """
        Initializes the wallet.

        Args:
            db: The database instance.
            default_balances: A dictionary of starting currencies and balances.
        """
        self.db = db
        if default_balances is None:
            self.default_balances = {"USDT": 1000.0}
        else:
            self.default_balances = default_balances

    def reset(self):
        """
        Resets the wallet to its default state.
        This clears all existing balances and trades from the database and
        re-populates the wallet with the default balances.
        """
        # Step 1: Clear all existing data in the database tables.
        self.db.reset_tables()

        # Step 2: Populate the wallet with the default starting balances.
        print(f"Populating wallet with default balances: {self.default_balances}")
        for currency, balance in self.default_balances.items():
            self.db.update_balance(currency, balance)

    def get_balance(self) -> Dict[str, float]:
        """Get the current balance from the database."""
        return self.db.get_balance()

    def update_balance(self, currency: str, new_balance: float):
        """Update the balance of a currency."""
        self.db.update_balance(currency, new_balance)