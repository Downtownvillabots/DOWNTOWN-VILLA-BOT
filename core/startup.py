import asyncio
import logging
from pyrogram import idle
from core.logging import setup_logging
from core.client import VillaClient
from core.config import LOG_CHANNEL

async def start_bot():
    setup_logging()
    logging.info("Starting DOWNTOWN VILLA BOT ENGINE...")
    bot = VillaClient()
    await bot.start()
    me = await bot.get_me()
    bot.username = me.username
    logging.info(f"Bot started: {me.first_name} (@{me.username})")

    # Send a start notification to the log channel (optional)
    try:
        await bot.send_message(LOG_CHANNEL, "DOWNTOWN VILLA BOT is now online.")
    except Exception as e:
        logging.warning(f"Could not send start message to log channel: {e}")

    logging.info("Bot idle. Waiting for commands...")
    await idle()

    # Cleanup on stop
    await bot.stop()
    logging.info("Bot stopped.")

def run():
    asyncio.run(start_bot())
