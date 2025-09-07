"""Test script to verify Telegram connection and channel access."""
import asyncio
from telethon import TelegramClient
import os
import sys

# Add the parent directory to Python path so we can import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.settings import settings
except Exception as e:
    print(f"❌ Error loading settings: {e}")
    print("Please make sure your .env file exists in the project root.")
    print("Check .env.example for the required format.")
    sys.exit(1)


async def test_telegram_connection():
    # Clean slate - remove any existing session
    session_file = "test_session"
    if os.path.exists(f"{session_file}.session"):
        os.remove(f"{session_file}.session")

    client = TelegramClient(session_file, settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)

    try:
        print("🔄 Starting Telegram client...")
        await client.start()
        print("✅ Telegram client started successfully!")

        # Test channel access
        print(f"🔍 Testing access to channel: {settings.TELEGRAM_CHANNEL_ID}")
        try:
            entity = await client.get_entity(settings.TELEGRAM_CHANNEL_ID)
            print(f"✅ Channel found: {entity.title if hasattr(entity, 'title') else 'Unknown'}")
            print(f"   Channel ID: {entity.id}")
            print(f"   Participants: {getattr(entity, 'participants_count', 'Unknown')}")
        except Exception as e:
            print(f"❌ Cannot access channel: {e}")
            return False

        # Test getting recent messages
        print("📨 Fetching recent messages...")
        try:
            messages = await client.get_messages(settings.TELEGRAM_CHANNEL_ID, limit=5)
            print(f"✅ Found {len(messages)} recent messages")
            for i, msg in enumerate(messages):
                print(f"   Message {i + 1}: {msg.message[:100] if msg.message else 'No text'}...")
        except Exception as e:
            print(f"❌ Cannot fetch messages: {e}")

        return True

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False
    finally:
        await client.disconnect()
        # Clean up test session
        if os.path.exists(f"{session_file}.session"):
            os.remove(f"{session_file}.session")


if __name__ == "__main__":
    print("🧪 Testing Telegram connection...")
    print(f"API ID: {settings.TELEGRAM_API_ID}")
    print(f"Channel: {settings.TELEGRAM_CHANNEL_ID}")

    success = asyncio.run(test_telegram_connection())

    if success:
        print("\n✅ Telegram connection test passed! Your bot should work.")
    else:
        print("\n❌ Telegram connection test failed. Check your credentials and channel access.")