#!/usr/bin/env python3
"""Create sample test data for the GUI to display."""

import sqlite3
import os
import json
from datetime import datetime, timedelta
import random
import sys

# Add project root to path to allow importing config settings
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

from config.settings import BASE_DIR


def create_test_database():
    """Create a test database with sample trading data."""

    # Use an absolute path to ensure the database is always in the project root
    db_path = BASE_DIR / "dry_run.db"

    if os.path.exists(db_path):
        response = input(f"Database {db_path} already exists. Overwrite? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create tables
    print("Creating tables...")

    # Trades table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_currency TEXT NOT NULL,
            quote_currency TEXT NOT NULL,
            telegram_channel TEXT,
            side TEXT NOT NULL,
            volume REAL NOT NULL,
            price REAL,
            ordertype TEXT NOT NULL,
            status TEXT NOT NULL,
            take_profit REAL,
            stop_loss REAL,
            take_profit_target INTEGER,
            leverage INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Wallet table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wallet (
            currency TEXT PRIMARY KEY,
            balance REAL NOT NULL
        )
    """)

    # LLM responses table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            base_currency TEXT,
            quote_currency TEXT,
            confidence INTEGER,
            entry_price_range TEXT,
            leverage TEXT,
            stop_loss REAL,
            take_profit_targets TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Sample trading pairs and channels
    pairs = [
        ("BTC", "USDT"), ("ETH", "USDT"), ("ADA", "USDT"),
        ("XRP", "USDT"), ("LTC", "USDT"), ("DOT", "USDT")
    ]

    channels = [
        "@testchannel", "@mycryptobottestchannel",
        "@universalcryptosignalss", "@demo_signals"
    ]

    print("Inserting sample trades...")

    # Insert sample trades
    for i in range(50):
        base, quote = random.choice(pairs)
        channel = random.choice(channels)
        side = random.choice(["buy", "sell"])
        volume = round(random.uniform(0.01, 2.0), 6)
        price = round(random.uniform(10.0, 50000.0), 2)
        ordertype = random.choice(["market", "limit"])
        status = random.choice(["simulated_open", "filled", "cancelled"])

        # Create timestamp in the past few days
        days_ago = random.randint(0, 7)
        hours_ago = random.randint(0, 23)
        timestamp = datetime.now() - timedelta(days=days_ago, hours=hours_ago)

        cursor.execute("""
            INSERT INTO trades (base_currency, quote_currency, telegram_channel, side, 
                              volume, price, ordertype, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (base, quote, channel, side, volume, price, ordertype, status, timestamp))

    print("Inserting sample wallet data...")

    # Insert sample wallet balances
    wallet_data = {
        "USDT": 1000.0,
        "BTC": 0.05,
        "ETH": 2.5,
        "ADA": 500.0,
        "XRP": 200.0,
        "USD": 500.0,
        "EUR": 300.0
    }

    for currency, balance in wallet_data.items():
        cursor.execute("INSERT INTO wallet (currency, balance) VALUES (?, ?)",
                       (currency, balance))

    print("Inserting sample LLM responses...")

    # Insert sample LLM responses
    for i in range(20):
        base, quote = random.choice(pairs)
        action = random.choice(["BUY", "SELL"])
        confidence = random.randint(70, 95)

        entry_range = [
            round(random.uniform(100, 1000), 2),
            round(random.uniform(1000, 2000), 2)
        ]

        take_profit_targets = [
            round(random.uniform(2000, 3000), 2),
            round(random.uniform(3000, 4000), 2),
            round(random.uniform(4000, 5000), 2)
        ]

        stop_loss = round(random.uniform(50, 150), 2)
        leverage = random.choice(["10x", "20x", "Cross 15x"])

        days_ago = random.randint(0, 5)
        timestamp = datetime.now() - timedelta(days=days_ago)

        cursor.execute("""
            INSERT INTO llm_responses (action, base_currency, quote_currency, confidence,
                                     entry_price_range, leverage, stop_loss, take_profit_targets, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (action, base, quote, confidence,
              json.dumps(entry_range), leverage, stop_loss,
              json.dumps(take_profit_targets), timestamp))

    conn.commit()
    conn.close()

    print(f"✅ Test database created: {db_path}")
    print(f"   - 50 sample trades")
    print(f"   - 7 wallet currencies")
    print(f"   - 20 LLM responses")
    print(f"\nNow run the GUI to see the data:")
    print(f"   python src/gui/gui_main.py")


def create_sample_log_file():
    """Create a sample log file."""
    # Place log file in the project root
    log_file = BASE_DIR / "trading_bot.log"

    sample_logs = [
        "2024-01-15 10:30:15 INFO [trading_bot] Starting trading application...",
        "2024-01-15 10:30:16 INFO [trading_bot] Settings: MODE=SPOT, EXCHANGE=MEXC, DRY_RUN=True",
        "2024-01-15 10:30:17 INFO [telegram_monitor] 👤 Starting Telegram User client...",
        "2024-01-15 10:30:18 INFO [telegram_monitor] ✅ Telegram User client started successfully",
        "2024-01-15 10:30:19 INFO [telegram_monitor] 🎯 LISTENING FOR NEW MESSAGES in channels: ['@testchannel']",
        "2024-01-15 10:31:22 INFO [trading_bot] 📱 NEW MESSAGE from 'testchannel':",
        "2024-01-15 10:31:23 INFO [signal_analyzer] Parsed signal: {'action': 'BUY', 'base_currency': 'BTC', 'confidence': 85}",
        "2024-01-15 10:31:24 INFO [pair_validator] Validated pair for MEXC (SPOT): BTCUSDT (BTC/USDT)",
        "2024-01-15 10:31:25 INFO [dry_run_trader] Current balances: {'USDT': 1000.0, 'BTC': 0.0}",
        "2024-01-15 10:31:26 INFO [trading_bot] Placing order: buy 0.020000 BTCUSDT at 45000.0 from testchannel",
        "2024-01-15 10:31:27 INFO [trading_bot] Order result: {'status': 'simulated_open'}",
        "2024-01-15 10:32:30 WARNING [trading_bot] Signal confidence 75 below threshold 80",
        "2024-01-15 10:33:45 INFO [trading_bot] 📱 NEW MESSAGE from 'testchannel':",
        "2024-01-15 10:33:46 INFO [trading_bot] Placing order: sell 0.020000 BTCUSDT at 46000.0 from testchannel",
        "2024-01-15 10:33:47 INFO [trading_bot] ✅ Successfully saved LLM response to the database.",
        "2024-01-15 10:35:12 ERROR [trading_bot] Insufficient USDT balance to place order: Need 900.00, have 100.00",
        "2024-01-15 10:36:22 INFO [trading_bot] Max daily trades reached",
    ]

    with open(log_file, 'w') as f:
        for log in sample_logs:
            f.write(log + '\n')

    print(f"✅ Sample log file created: {log_file}")


def main():
    print("🧪 Creating test data for Trading Bot GUI...")
    print()

    try:
        create_test_database()
        create_sample_log_file()

        print(f"\n🎉 Test data created successfully!")
        print(f"\nNext steps:")
        print(f"1. Run the GUI: python src/gui/gui_main.py")
        print(f"2. Click through the tabs to see sample data")
        print(f"3. Try the filters and sorting features")

    except Exception as e:
        print(f"❌ Error creating test data: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()