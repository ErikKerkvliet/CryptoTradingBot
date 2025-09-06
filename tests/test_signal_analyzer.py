import asyncio
from src.signal_analyzer import SignalAnalyzer

def test_regex_example_long():
    analyzer = SignalAnalyzer(openai_api_key="test")
    msg = "LONG #BTC/USDT Entry: 65000-64500 TP: 66000, 67000, 68000 SL: 63000"
    parsed = asyncio.run(analyzer.analyze(msg))
    assert parsed["action"] == "BUY"
    assert parsed["base_currency"] == "BTC"
    assert parsed["quote_currency"] == "USDT"
    assert parsed["entry_price_range"] == [64500.0, 65000.0]
    assert parsed["take_profit_levels"] == [66000.0, 67000.0, 68000.0]
    assert parsed["stop_loss"] == 63000.0

def test_regex_example_short():
    analyzer = SignalAnalyzer(openai_api_key="test")
    msg = "SHORT #ETH/USDT 25x Entry: 3200 Targets: 3100, 3000, 2900 SL: 3350"
    parsed = asyncio.run(analyzer.analyze(msg))
    assert parsed["action"] == "SELL"
    assert parsed["base_currency"] == "ETH"
    assert parsed["leverage"] == 25
    assert parsed["entry_price"] == 3200.0
    assert parsed["take_profit_levels"] == [3100.0, 3000.0, 2900.0]
    assert parsed["stop_loss"] == 3350.0