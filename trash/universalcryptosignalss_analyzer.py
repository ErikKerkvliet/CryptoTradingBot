"""Signal analyzer for the '@universalcryptosignalss' Telegram channel."""
from typing import Dict, Any
from src.analyzers.default_analyzer import DefaultAnalyzer
from src.utils.exceptions import SignalParseError

class UniversalCryptoSignalsSAnalyzer(DefaultAnalyzer):
    """
    A dedicated parser for messages from the 'universalcryptossignals' channel.

    This class can be customized to override the default regex parsing
    if the message format from this specific channel is different or requires
    special handling. For now, it inherits the default behavior.
    """
    async def analyze(self, message: str) -> Dict[str, Any]:
        """
        Analyzes a message from Universal Crypto Signals.

        Args:
            message: The raw text message from Telegram.

        Returns:
            A dictionary containing the structured trading signal.

        Raises:
            SignalParseError: If the message cannot be parsed into a valid signal.
        """
        try:
            return await super().analyze(message)
        except SignalParseError as e:
            raise SignalParseError(f"Failed to parse with UniversalCryptoSignalsSAnalyzer: {e}")