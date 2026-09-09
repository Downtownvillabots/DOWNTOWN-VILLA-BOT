import asyncio
import logging
from pyrogram import idle
from core.logging import setup_logging
from core.client import VillaClient
from plugins.log_channel import set_bot, bot_started, send_log
from database import db_manager

async def start_bot():
    setup_logging()
    logging.info("Starting DOWNTOWN VILLA BOT ENGINE...")
    bot = VillaClient()
    set_bot(bot)
    await bot.start()
    me = await bot.get_me()
    bot.username = me.username
    logging.info(f"Bot started: {me.first_name} (@{me.username})")

    # Initialize database connections (optional)
    try:
        await db_manager.initialize()
        if db_manager.is_db_enabled:
            logging.info("Database manager initialized.")
            await send_log("🗄️ Database connections established.")
        else:
            logging.info("No databases configured – running without database features.")
    except Exception as e:
        logging.error(f"Database initialization failed: {e}")

    await bot_started()

    logging.info("Bot idle. Waiting for commands...")
    await idle()

    # Cleanup
    await db_manager.close()
    await bot.stop()
    logging.info("Bot stopped.")

def run():
    asyncio.run(start_bot())
