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

    try:
        await db_manager.initialize()
        if db_manager.is_db_enabled:
            logging.info("Database connected.")
            await send_log("🗄️ Database connected.")
        else:
            logging.warning("Database not enabled. Check DATABASE_URI setting.")
    except Exception as e:
        logging.error(f"Database initialization failed: {e}")

    await bot_started()

    logging.info("Bot idle. Waiting for commands...")
    await idle()

    await db_manager.close()
    await bot.stop()
    logging.info("Bot stopped.")

def run():
    asyncio.run(start_bot())
