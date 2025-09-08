"""Monitors the Telegram channel for new messages using Telethon User API only."""
from __future__ import annotations
from telethon import TelegramClient, events
from typing import Callable, Awaitable, List, Union
import asyncio
import logging
import os

class TelegramMonitor:
    """Wraps Telethon client and provides a callback hook for new messages.

    Uses User Account API only (TELEGRAM_API_ID + TELEGRAM_API_HASH).
    """
    def __init__(self, api_id: int, api_hash: str, channels: List[Union[int, str]], logger: logging.Logger):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channels = channels
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

    async def start(self, on_message: Callable[[str, str], Awaitable[None]]):
        try:
            self.logger.info("👤 Starting Telegram User client...")
            await self.client.start()
            self.logger.info("✅ Telegram User client started successfully")

            # Test if we can access all the channels
            for channel in self.channels:
                try:
                    entity = await self.client.get_entity(channel)
                    self.logger.info(f"✅ Successfully connected to channel: '{getattr(entity, 'title', 'Unknown')}' (ID: {entity.id})")
                except Exception as e:
                    self.logger.error(f"❌ Failed to access channel '{channel}': {e}")
                    self.logger.error("Make sure your account has access to this channel and the ID is correct.")
                    return

            # Set up new message handler for all specified channels
            @self.client.on(events.NewMessage(chats=self.channels))
            async def handler(event):
                try:
                    text = event.message.message
                    if text and text.strip():
                        # Get a user-friendly name for the source channel for logging/DB
                        source_entity = await event.get_chat()
                        source_channel_name = getattr(source_entity, 'username', str(event.chat_id))

                        self.logger.info(f"📱 NEW MESSAGE from '{source_channel_name}':")
                        self.logger.info(f"   Content: {text[:200]}...")

                        # Process the message, passing the specific channel it came from
                        await on_message(text.strip(), source_channel_name)

                    else:
                        self.logger.debug("Received message without text content (might be media/sticker)")

                except Exception as e:
                    self.logger.exception(f"❌ Error processing new message: {e}")

            self.logger.info(f"🎯 LISTENING FOR NEW MESSAGES in channels: {self.channels}")
            self.logger.info("✅ Bot is ready! Send a message to a monitored channel to test...")
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