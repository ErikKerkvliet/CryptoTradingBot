"""Fixed Telegram monitor with robust message handling."""
from __future__ import annotations
from telethon import TelegramClient, events
from typing import Callable, Awaitable, List, Union
import asyncio
import logging
import os


class TelegramMonitor:
    """Enhanced Telegram monitor with better message handling and debugging."""

    def __init__(self, api_id: int, api_hash: str, channels: List[Union[int, str]], logger: logging.Logger):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channels = channels
        self.logger = logger
        self.connected_entities = []
        self.message_count = 0

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
        """Start the Telegram monitor and set up message handling."""
        try:
            self.logger.info("👤 Starting Telegram User client...")
            await self.client.start()

            # Check what type of account we're using
            me = await self.client.get_me()
            if me.bot:
                self.logger.error("❌ Logged in as BOT account! Bot accounts can't listen to channel messages.")
                self.logger.error("   Make sure you're using USER API credentials (api_id/api_hash), not bot token.")
                raise Exception("Bot account detected - need user account for channel monitoring")

            self.logger.info("✅ Telegram User client started successfully")
            self.logger.info(f"👤 Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'no_username'})")

            # Get and validate all channels first
            self.logger.info("🔍 Connecting to channels...")
            for channel in self.channels:
                try:
                    entity = await self.client.get_entity(channel)
                    self.connected_entities.append(entity)

                    # Log detailed channel info
                    self.logger.info(f"✅ Connected to channel: '{getattr(entity, 'title', 'Unknown')}'")
                    self.logger.info(f"   Channel ID: {entity.id}")
                    self.logger.info(f"   Username: @{getattr(entity, 'username', 'None')}")
                    self.logger.info(f"   Type: {type(entity).__name__}")

                    # Test message access
                    try:
                        recent_messages = await self.client.get_messages(entity, limit=1)
                        if recent_messages:
                            self.logger.info(f"   ✅ Can access message history")
                        else:
                            self.logger.info(f"   ⚠️ No message history available")
                    except Exception as e:
                        self.logger.warning(f"   ⚠️ Cannot read message history: {e}")
                        self.logger.info(f"   ℹ️ This is normal for many channels - new messages will still work")

                except Exception as e:
                    self.logger.error(f"❌ Failed to access channel '{channel}': {e}")
                    self.logger.error("   Make sure your account has access to this channel and the ID is correct.")

            if not self.connected_entities:
                self.logger.error("❌ No accessible channels found! Cannot continue.")
                return

            self.logger.info(f"🎯 Successfully connected to {len(self.connected_entities)} channels")

            # Set up message handler with detailed error handling
            @self.client.on(events.NewMessage(chats=self.connected_entities))
            async def message_handler(event):
                """Handle new messages with comprehensive error handling and logging."""
                try:
                    self.message_count += 1

                    # Get message text
                    text = event.message.message

                    # Log raw event details for debugging
                    self.logger.debug(f"📡 Raw message event #{self.message_count}:")
                    self.logger.debug(f"   Chat ID: {event.chat_id}")
                    self.logger.debug(f"   Message ID: {event.message.id}")
                    self.logger.debug(f"   Date: {event.message.date}")
                    self.logger.debug(f"   Text length: {len(text or '')}")
                    self.logger.debug(f"   Has media: {bool(event.message.media)}")
                    self.logger.debug(f"   Sender ID: {event.sender_id}")

                    if text and text.strip():
                        # Get chat info for source channel name
                        try:
                            source_entity = await event.get_chat()

                            # Determine the best channel name to use
                            # Priority: username -> title -> chat_id
                            source_channel_name = (
                                    getattr(source_entity, 'username', None) or
                                    getattr(source_entity, 'title', '').replace(' ', '_').lower() or
                                    str(event.chat_id)
                            )

                            # Remove @ prefix if present for consistency
                            if source_channel_name.startswith('@'):
                                source_channel_name = source_channel_name[1:]

                            self.logger.info(f"📱 NEW MESSAGE #{self.message_count} from '{source_channel_name}':")
                            self.logger.info(f"   Channel: {getattr(source_entity, 'title', 'Unknown')}")
                            self.logger.info(f"   Content preview: {text[:200]}...")
                            self.logger.info(f"   Full length: {len(text)} characters")

                            # Call the message processing function
                            try:
                                await on_message(text.strip(), source_channel_name)
                                self.logger.debug(f"✅ Message #{self.message_count} processed successfully")
                            except Exception as process_error:
                                self.logger.error(
                                    f"❌ Error in message processing for message #{self.message_count}: {process_error}")
                                # Don't re-raise - we want to keep listening for other messages

                        except Exception as get_chat_error:
                            self.logger.error(
                                f"❌ Error getting chat info for message #{self.message_count}: {get_chat_error}")
                            # Fallback - still try to process the message with chat ID as channel name
                            try:
                                await on_message(text.strip(), str(event.chat_id))
                            except Exception as fallback_error:
                                self.logger.error(f"❌ Fallback processing also failed: {fallback_error}")

                    else:
                        self.logger.debug(f"📡 Message #{self.message_count} has no text content (media-only or empty)")

                except Exception as e:
                    self.logger.exception(f"❌ Critical error processing message #{self.message_count}: {e}")
                    self.logger.error(
                        f"   Event details - Chat: {getattr(event, 'chat_id', 'unknown')}, Message ID: {getattr(event.message, 'id', 'unknown')}")
                    # Don't re-raise - keep the bot running

            # Set up a catch-all debug handler
            @self.client.on(events.NewMessage())
            async def debug_handler(event):
                """Catch-all handler to debug missed messages."""
                # Only log if it's from one of our target channel IDs but wasn't caught by main handler
                target_ids = [entity.id for entity in self.connected_entities]
                if event.chat_id in target_ids:
                    self.logger.debug(f"🔍 DEBUG: Message in target channel {event.chat_id} caught by debug handler")
                    self.logger.debug(f"   This might indicate an issue with the main message handler")

            self.logger.info("✅ Message handlers registered successfully!")

            self.logger.info(f"🎯 LISTENING FOR NEW MESSAGES in {len(self.connected_entities)} channels:")
            for entity in self.connected_entities:
                self.logger.info(f"   📺 {getattr(entity, 'title', 'Unknown')} (ID: {entity.id})")

            self.logger.info("✅ Bot is ready! Send a message to a monitored channel to test...")
            self.logger.info("   (Press Ctrl+C to stop)")

            # Keep the client running and listening for new messages
            await self.client.run_until_disconnected()

        except Exception as e:
            self.logger.exception(f"❌ Error starting Telegram client: {e}")
            raise

    async def stop(self):
        """Stop the Telegram monitor and disconnect."""
        try:
            if self.client:
                await self.client.disconnect()
                self.logger.info(f"📴 Telegram client disconnected (processed {self.message_count} messages total)")
        except Exception as e:
            self.logger.error(f"Error disconnecting Telegram client: {e}")