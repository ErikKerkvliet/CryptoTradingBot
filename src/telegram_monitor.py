"""Monitors the Telegram channel for new messages using Telethon."""
from __future__ import annotations
from telethon import TelegramClient, events
from typing import Callable, Awaitable
import asyncio
import logging

class TelegramMonitor:
    """Wraps Telethon client and provides a callback hook for new messages."""
    def __init__(self, api_id: int, api_hash: str, channel: str, logger: logging.Logger):
        self.api_id = api_id
        self.api_hash = api_hash
        self.channel = channel
        self.logger = logger
        self.client = TelegramClient("trading_bot_session", api_id, api_hash)

    async def start(self, on_message: Callable[[str], Awaitable[None]]):
        await self.client.start()

        self.logger.info("Telegram client started")
        @self.client.on(events.NewMessage(chats=self.channel))
        async def handler(event):
            text = event.message.message
            self.logger.info(f"New telegram message: {text[:200]}")
            try:
                await on_message(text)
            except Exception as e:
                self.logger.exception("Error in on_message callback")

        self.logger.info(f"Listening to channel {self.channel}")
        await self.client.run_until_disconnected()

    async def stop(self):
        await self.client.disconnect()