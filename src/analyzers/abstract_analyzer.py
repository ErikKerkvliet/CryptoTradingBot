"""Abstract base class for signal analyzers."""
from abc import ABC, abstractmethod
from typing import Dict, Any

class AbstractAnalyzer(ABC):
    """Abstract base class for all signal analyzers."""

    @abstractmethod
    async def analyze(self, message: str) -> Dict[str, Any]:
        """
        Analyzes a message and returns a structured signal.

        Args:
            message: The message to analyze.

        Returns:
            A dictionary representing the parsed signal.
        """
        pass