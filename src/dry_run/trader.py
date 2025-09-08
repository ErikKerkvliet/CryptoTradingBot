"""Simulates a Kraken trader for dry-run mode."""
from typing import Dict, Any, Optional
import httpx
from ..utils.exceptions import InsufficientBalanceError
from .database import DryRunDatabase
from .wallet import VirtualWallet


class DryRunTrader:
    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.db = DryRunDatabase()
        self.wallet = VirtualWallet(self.db)
        self.wallet.reset()

        self._client = httpx.AsyncClient(timeout=15)

    async def get_balance(self) -> Dict[str, float]:
        """Get the virtual wallet balance."""
        return self.wallet.get_balance()

    async def get_market_price(self, pair: str) -> float:
        """Get the current market price from Kraken."""
        try:
            url = f"{self.BASE_URL}/0/public/Ticker"
            params = {"pair": pair}
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if data.get("result"):
                # Get the last trade price
                return float(list(data["result"].values())[0]["c"][0])
            raise ValueError("Invalid response from Kraken API")
        except Exception as e:
            print(f"Error fetching market price: {e}")
            return 1.0  # Fallback price

    async def place_order(self, pair: str, side: str, volume: float, ordertype: str = "market",
                          price: Optional[float] = None, telegram_channel: Optional[str] = None) -> Dict[str, Any]:
        """Simulate placing an order and record it in the database."""
        balances = self.wallet.get_balance()
        base_currency, quote_currency = pair.split('/')

        if ordertype == "market" and price is None:
            kraken_pair = pair.replace("/", "")
            price = await self.get_market_price(kraken_pair)

        cost = volume * price if price else 0

        if side.lower() == "buy":
            if balances.get(quote_currency, 0) < cost:
                raise InsufficientBalanceError("Insufficient funds for the trade.")

            # Simulate the trade
            self.wallet.update_balance(quote_currency, balances[quote_currency] - cost)
            self.wallet.update_balance(base_currency, balances.get(base_currency, 0) + volume)
        else:  # Sell
            if balances.get(base_currency, 0) < volume:
                raise InsufficientBalanceError("Insufficient funds for the trade.")

            # Simulate the trade
            self.wallet.update_balance(base_currency, balances[base_currency] - volume)
            self.wallet.update_balance(quote_currency, balances.get(quote_currency, 0) + cost)

        trade_data = {
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "side": side,
            "volume": volume,
            "price": price,
            "ordertype": ordertype,
            "telegram_channel": telegram_channel
        }
        self.db.add_trade(trade_data)

        return {"status": "simulated", **trade_data}

    async def close(self):
        """Close the database and client connections."""
        self.db.close()
        await self._client.aclose()