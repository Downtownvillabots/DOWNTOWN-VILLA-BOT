# core/startup.py
import asyncio
import logging
from pyrogram import idle
from core.logging import setup_logging
from core.client import VillaClient
from plugins.log_channel import set_bot, bot_started

async def start_bot():
    setup_logging()
    logging.info("Starting DOWNTOWN VILLA BOT ENGINE...")
    bot = VillaClient()
    set_bot(bot)  # allow log channel plugin to use this client
    await bot.start()
    me = await bot.get_me()
    bot.username = me.username
    logging.info(f"Bot started: {me.first_name} (@{me.username})")

    # Send startup notification to Telegram logging channel (only if LOG_CHANNEL_ID is set)
    await bot_started()

    logging.info("Bot idle. Waiting for commands...")
    await idle()

    # Cleanup on stop
    await bot.stop()
    logging.info("Bot stopped.")

def run():
    asyncio.run(start_bot())
