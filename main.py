"""Main application entrypoint orchestrating all components."""
import asyncio
from config.settings import settings
from src.utils.logger import setup_logger
from src.telegram_monitor import TelegramMonitor
from src.signal_analyzer import SignalAnalyzer
from src.pair_validator import PairValidator
from src.kraken_trader import KrakenTrader
from src.utils.exceptions import InsufficientBalanceError, PairNotFoundError, SignalParseError

logger = setup_logger(level=settings.LOG_LEVEL)

class TradingApp:
    def __init__(self):
        self.settings = settings
        self.logger = logger
        self.analyzer = SignalAnalyzer(settings.OPENAI_API_KEY)
        self.validator = PairValidator()
        self.trader = KrakenTrader(settings.KRAKEN_API_KEY,
        settings.KRAKEN_API_SECRET, dry_run=settings.DRY_RUN)
        self.telegram = TelegramMonitor(settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH, settings.TELEGRAM_CHANNEL_ID, self.logger)
        self.daily_trades = 0

    async def on_message(self, message: str):
        try:
            parsed = await self.analyzer.analyze(message)
            self.logger.info(f"Parsed signal: {parsed}")
        except SignalParseError:
            self.logger.warning("Could not parse signal")
            return

        conf = parsed.get("confidence", 0) or 0
        if conf < self.settings.MIN_CONFIDENCE_THRESHOLD:
            self.logger.info(f"Signal confidence {conf} below threshold {self.settings.MIN_CONFIDENCE_THRESHOLD}")
            return

        if self.daily_trades >= self.settings.MAX_DAILY_TRADES:
            self.logger.warning("Max daily trades reached")
            return

        base = parsed.get("base_currency")
        quote = parsed.get("quote_currency") or "USDC"

        try:
            base, quote = await self.validator.validate_and_convert(base, quote)
        except PairNotFoundError:
            self.logger.warning("Pair not available on Kraken")
            return

        # compute position size
        balances = await self.trader.get_balance()
        quote_balance = balances.get(quote) or balances.get(quote + "S") or 0.0
        max_pct = self.settings.MAX_POSITION_SIZE_PERCENT / 100.0
        # simple allocation: use max_pct of quote balance
        order_value = quote_balance * max_pct
        if order_value <= 0:
            self.logger.warning("No available balance for trading")
            return

        # approximate volume: if entry price present, use it; else require market order and estimate
        entry = parsed.get("entry_price")
        if entry is None and parsed.get("entry_price_range"):
            entry = sum(parsed.get("entry_price_range")) / 2.0
        if entry is None:
            # market order: we will place market and volume based on available funds and market price (not implemented: fetch ticker)
            self.logger.info("No entry given; placing market order using estimated market price")

        volume = order_value / max(1e-8, (entry or 1.0))
        pair_str = f"{base}/{quote}"
        # note: mapping to Kraken altname is done by PairValidator - here we supply altname as pair_str is fine if Kraken accepts wsname
        side = "buy" if parsed.get("action") == "BUY" else "sell"
        try:
            # simple market order
            res = await self.trader.place_order(pair_str, side.upper(), volume,
            ordertype=("limit" if entry else "market"), price=entry)
            self.logger.info(f"Order result: {res}")
            if not self.settings.DRY_RUN:
                self.daily_trades += 1
        except InsufficientBalanceError:
            self.logger.warning("Insufficient balance to place order")
        except Exception:
            self.logger.exception("Order failed")

    async def run(self):
        await self.telegram.start(self.on_message)

if __name__ == "__main__":
    app = TradingApp()
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.info("Shutting down")