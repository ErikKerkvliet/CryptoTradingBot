#!/usr/bin/env python3
"""Simple test script to verify Telegram connection and channel access."""
import asyncio
import os
import sys

# Add the parent directory to Python path so we can import config
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)


def check_env_file():
    """Check if .env file exists and has required variables."""
    env_path = os.path.join(project_root, '.env')
    if not os.path.exists(env_path):
        print(f"❌ .env file not found at {env_path}")
        print("Please create .env file from .env.example")
        return False

    print(f"✅ .env file found at {env_path}")

    # Check if required variables are present
    required_vars = [
        'TELEGRAM_API_ID',
        'TELEGRAM_API_HASH',
        'TELEGRAM_CHANNEL_ID'
    ]

    missing_vars = []
    with open(env_path, 'r') as f:
        env_content = f.read()
        for var in required_vars:
            if f"{var}=" not in env_content or f"{var}=your_" in env_content:
                missing_vars.append(var)

    if missing_vars:
        print(f"❌ Missing or not configured variables: {', '.join(missing_vars)}")
        return False

    print("✅ All required Telegram variables seem to be set")
    return True


async def test_telegram_connection():
    """Test Telegram connection."""
    try:
        from config.settings import settings
        print("✅ Settings loaded successfully")
    except Exception as e:
        print(f"❌ Error loading settings: {e}")
        return False

    # Import telethon
    try:
        from telethon import TelegramClient
        print("✅ Telethon imported successfully")
    except ImportError as e:
        print(f"❌ Error importing Telethon: {e}")
        print("Run: pip install telethon")
        return False

    # Clean up any existing test session
    session_file = "test_connection_session"
    for ext in [".session", ".session-journal"]:
        if os.path.exists(session_file + ext):
            os.remove(session_file + ext)

    client = TelegramClient(session_file, settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)

    try:
        print("🔄 Starting Telegram client...")
        await client.start()
        print("✅ Telegram client started successfully!")

        # Test channel access
        print(f"🔍 Testing access to channel: {settings.TELEGRAM_CHANNEL_ID}")
        try:
            entity = await client.get_entity(settings.TELEGRAM_CHANNEL_ID)
            print(f"✅ Channel found!")
            print(f"   Title: {getattr(entity, 'title', 'Unknown')}")
            print(f"   ID: {entity.id}")
            print(f"   Type: {type(entity).__name__}")

            if hasattr(entity, 'participants_count'):
                print(f"   Participants: {entity.participants_count}")

        except Exception as e:
            print(f"❌ Cannot access channel: {e}")
            print("Make sure:")
            print("  1. The channel ID is correct (starts with @ or is numeric)")
            print("  2. Your account has access to this channel")
            print("  3. The channel exists and is public or you're a member")
            return False

        # Test getting recent messages (this might fail and that's OK)
        print("📨 Testing message history access...")
        try:
            messages = await client.get_messages(settings.TELEGRAM_CHANNEL_ID, limit=3)
            print(f"✅ Can read message history! Found {len(messages)} recent messages")
            for i, msg in enumerate(messages):
                if msg.message:
                    preview = msg.message[:100].replace('\n', ' ')
                    print(f"   Message {i + 1}: {preview}...")
                else:
                    print(f"   Message {i + 1}: [No text content]")
        except Exception as e:
            print(f"⚠️  Cannot read message history: {e}")
            print("ℹ️  This is NORMAL for many channels! Your bot will still receive NEW messages.")

        # Test if we can send messages (optional)
        print("📤 Testing send permissions...")
        try:
            # Don't actually send, just check permissions
            me = await client.get_me()
            print(f"✅ Logged in as: {me.username or me.first_name}")
            print("ℹ️  Send permissions not tested (would require actually sending)")
        except Exception as e:
            print(f"⚠️  Could not check user info: {e}")

        print("\n✅ Telegram connection test PASSED!")
        print("🎯 Your bot is ready to receive NEW messages from the channel")
        print("📝 Even if message history access failed, new message monitoring will work!")
        return True

    except Exception as e:
        print(f"❌ Connection failed: {e}")
        if "invalid api_id/api_hash" in str(e).lower():
            print("❌ Check your TELEGRAM_API_ID and TELEGRAM_API_HASH in .env")
        elif "phone number" in str(e).lower():
            print("❌ You need to verify your phone number first")
        return False
    finally:
        await client.disconnect()
        # Clean up test session
        for ext in [".session", ".session-journal"]:
            if os.path.exists(session_file + ext):
                try:
                    os.remove(session_file + ext)
                except:
                    pass


def main():
    print("🧪 Testing Telegram connection...\n")

    # First check .env file
    if not check_env_file():
        print("\n❌ Environment setup failed. Fix .env file first.")
        return

    try:
        # Load and validate settings
        from config.settings import settings
        print(f"📋 Configuration:")
        print(f"   API ID: {settings.TELEGRAM_API_ID}")
        print(f"   Channel: {settings.TELEGRAM_CHANNEL_ID}")
        print(f"   DRY_RUN: {settings.DRY_RUN}")
        print()

        # Run async test
        success = asyncio.run(test_telegram_connection())

        if success:
            print("\n🎉 All tests passed! Your Telegram bot should work.")
            print("You can now run: python main.py")
        else:
            print("\n❌ Tests failed. Please fix the issues above.")

    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()