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
        """
        Dynamically loads all analyzer classes from the 'analyzers' directory
        based on a '{channel_name}_analyzer.py' naming convention.
        """
        analyzer_dir = os.path.join(os.path.dirname(__file__), "analyzers")
        for filename in os.listdir(analyzer_dir):
            # We are looking for files like 'channelname_analyzer.py'
            if filename.endswith("_analyzer.py") and not filename.startswith("__"):
                # Extract the channel name, e.g., 'universalcryptosignalss'
                channel_key = filename.replace("_analyzer.py", "")
                module_name = f"src.analyzers.{filename[:-3]}"
                try:
                    module = importlib.import_module(module_name)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if isinstance(attr, type) and issubclass(attr, AbstractAnalyzer) and attr is not AbstractAnalyzer:
                            # Instantiate and store the analyzer, keyed by the channel name
                            self._analyzers[channel_key] = attr()
                            break  # Assume one analyzer class per file
                except ImportError as e:
                    print(f"Error loading analyzer from {filename}: {e}")

    async def analyze(self, message: str, channel: str) -> Dict[str, Any]:
        """
        Analyzes a message using a channel-specific analyzer if available,
        otherwise falls back to the DefaultAnalyzer.
        """
        # Clean channel name to use as a key, e.g., '@my_channel' -> 'my_channel'
        analyzer_key = channel.replace('@', '')

        analyzer = self._analyzers.get(analyzer_key)

        if analyzer:
            # Use the specific analyzer found for this channel
            return await analyzer.analyze(message)
        else:
            # Fallback to the default regex-based analyzer
            return await DefaultAnalyzer().analyze(message)