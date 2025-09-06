class TradingBotError(Exception):
    """Base exception for trading bot."""


class PairNotFoundError(TradingBotError):
    """Raised when a pair is not available on Kraken."""


class InsufficientBalanceError(TradingBotError):
    """Raised when account balance is insufficient for an order."""


class SignalParseError(TradingBotError):
    """Raised when a signal cannot be parsed."""