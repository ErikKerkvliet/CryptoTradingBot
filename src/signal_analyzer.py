"""SignalAnalyzer parses Telegram messages into structured trading signals."""
from __future__ import annotations
from typing import Dict, Any
import importlib
import os
from .utils.exceptions import SignalParseError
from .analyzers.abstract_analyzer import AbstractAnalyzer
from .analyzers.default_analyzer import DefaultAnalyzer

class SignalAnalyzer:
    """
    Acts as a factory to load and delegate to the appropriate analyzer
    based on the channel name.
    """

    def __init__(self):
        self._analyzers: Dict[str, AbstractAnalyzer] = {}
        self._load_analyzers()

    def _load_analyzers(self):
        """Dynamically loads all analyzer classes from the 'analyzers' directory."""
        analyzer_dir = os.path.join(os.path.dirname(__file__), "analyzers")
        for filename in os.listdir(analyzer_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = f"src.analyzers.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, AbstractAnalyzer) and attr is not AbstractAnalyzer and attr is not DefaultAnalyzer:
                            # Instantiate and store the analyzer, keyed by its class name (lowercased)
                            # e.g., 'SomeChannelAnalyzer' becomes 'somechannelanalyzer'
                            self._analyzers[attr.__name__.lower()] = attr()
                except ImportError as e:
                    print(f"Error loading analyzer from {filename}: {e}")

    async def analyze(self, message: str, channel: str) -> Dict[str, Any]:
        """
        Analyzes a message using a channel-specific analyzer if available,
        otherwise falls back to the DefaultAnalyzer.
        """
        # Formatter channel name to match analyzer class name convention
        # e.g., '@my_channel' becomes 'my_channel_analyzer'
        analyzer_key = f"{channel.replace('@', '').lower()}_analyzer"

        analyzer = self._analyzers.get(analyzer_key)

        if analyzer:
            return await analyzer.analyze(message)
        else:
            # Fallback to default analyzer
            return await DefaultAnalyzer().analyze(message)