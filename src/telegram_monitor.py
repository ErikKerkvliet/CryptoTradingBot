"""Monitors the Telegram channel for new messages using Telethon User API only."""
from __future__ import annotations
from telethon import TelegramClient, events
from typing import Callable, Awaitable
import asyncio
import logging
import os

class TelegramMonitor:
    """Wraps Telethon client and provides a callback hook for new messages.

    Uses User Account API only (TELEGRAM_API_ID + TELEGRAM_API_HASH).
    """
    def __init__(self, api_id: int, api_hash: str, channel: str, logger: logging.Logger):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel = channel
        self.logger = logger

        # Ensure sessions directory exists and has proper permissions
        sessions_dir = "sessions"
        if not os.path.exists(sessions_dir):
            os.makedirs(sessions_dir, mode=0o755)

        session_file = os.path.join(sessions_dir, "trading_user_session")

        # Remove existing session file if it has permission issues
        for ext in [".session", ".session-journal"]:
            session_path = session_file + ext
            if os.path.exists(session_path):
                try:
                    os.chmod(session_path, 0o644)
                except PermissionError:
                    self.logger.warning(f"Removing corrupted session file: {session_path}")
                    try:
                        os.remove(session_path)
                    except:
                        pass

        self.client = TelegramClient(session_file, api_id, api_hash)

    async def start(self, on_message: Callable[[str], Awaitable[None]]):
        try:
            self.logger.info("👤 Starting Telegram User client...")
            await self.client.start()
            self.logger.info("✅ Telegram User client started successfully")

            # Test if we can access the channel
            try:
                entity = await self.client.get_entity(self.channel)
                self.logger.info(f"✅ Successfully connected to channel: {getattr(entity, 'title', 'Unknown')}")
                self.logger.info(f"   Channel ID: {entity.id}")
                self.logger.info(f"   Channel type: {type(entity).__name__}")

            except Exception as e:
                self.logger.error(f"❌ Failed to access channel {self.channel}: {e}")
                self.logger.error("Make sure:")
                self.logger.error("  1. Your account has access to this channel")
                self.logger.error("  2. The channel ID is correct")
                self.logger.error("  3. You are a member of the channel (for private channels)")
                return

            # Try to get recent messages (this might fail, but that's OK)
            try:
                self.logger.info("🔍 Testing message access...")
                messages = await self.client.get_messages(self.channel, limit=1)
                if messages:
                    self.logger.info(f"✅ Can read messages. Latest message preview: {messages[0].message[:50] if messages[0].message else 'No text'}...")
                else:
                    self.logger.info("ℹ️  No recent messages found")
            except Exception as e:
                self.logger.warning(f"⚠️  Cannot read message history: {e}")
                self.logger.info("ℹ️  This is normal for some channels. New messages will still be received!")

            # Set up new message handler
            @self.client.on(events.NewMessage(chats=self.channel))
            async def handler(event):
                try:
                    text = event.message.message
                    if text and text.strip():
                        self.logger.info(f"📱 NEW MESSAGE RECEIVED:")
                        self.logger.info(f"   Content: {text[:200]}...")
                        self.logger.info(f"   From: {getattr(event.message.sender, 'username', 'Unknown')}")
                        self.logger.info(f"   Time: {event.message.date}")

                        # Process the message
                        await on_message(text.strip())

                    else:
                        self.logger.debug("Received message without text content (might be media/sticker)")

                except Exception as e:
                    self.logger.exception(f"❌ Error processing new message: {e}")

            self.logger.info(f"🎯 LISTENING FOR NEW MESSAGES in {self.channel}")
            self.logger.info("✅ Bot is ready! Send a message to the channel to test...")
            self.logger.info("   (Press Ctrl+C to stop)")

            # Keep the client running and listening for new messages
            await self.client.run_until_disconnected()

        except Exception as e:
            self.logger.exception(f"❌ Error starting Telegram client: {e}")
            raise

    async def stop(self):
        try:
            if self.client:
                await self.client.disconnect()
                self.logger.info("📴 Telegram client disconnected")
        except Exception as e:
            self.logger.error(f"Error disconnecting Telegram client: {e}")

    async def test_send_message(self, message: str):
        """Send a test message to the channel (if you have send permissions)"""
        try:
            await self.client.send_message(self.channel, message)
            self.logger.info(f"✅ Test message sent: {message}")
            return True
        except Exception as e:
            self.logger.warning(f"⚠️  Cannot send messages to this channel: {e}")
            self.logger.info("This is normal if you don't have send permissions")
            return False