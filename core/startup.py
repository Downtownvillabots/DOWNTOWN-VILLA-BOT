import asyncio
import logging
from aiohttp import web
from pyrogram import idle
from core.logging import setup_logging
from core.client import VillaClient
from plugins.log_channel import set_bot, bot_started, send_log
from database import db_manager, db_registry
from core.config import LOG_CHANNEL, PORT

async def start_bot():
    setup_logging()
    logging.info("Starting DOWNTOWN VILLA BOT ENGINE...")

    bot = VillaClient()
    set_bot(bot)
    await bot.start()

    me = await bot.get_me()
    bot.username = me.username
    logging.info(f"Bot started: {me.first_name} (@{me.username})")

    # Minimal web server for Render
    app = web.Application()
    app.router.add_get("/", lambda request: web.Response(text="DOWNTOWN VILLA BOT is running."))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logging.info(f"Web server started on port {PORT}")

    # Initialize database layer
    try:
        await db_manager.initialize()
        if db_manager.is_db_enabled:
            shard_count = db_registry.get_media_shard_count()
            logging.info(f"Database connected. Media shards: {shard_count}")
            await send_log(f"🗄️ Database connected. Media shards: {shard_count}")
        else:
            logging.warning("Database not enabled. Check DATABASE_URI.")
    except Exception as e:
        logging.error(f"Database initialization failed: {e}")

    await bot_started()

    logging.info("Bot idle. Waiting for commands...")
    await idle()

    await runner.cleanup()
    await db_manager.close()
    await bot.stop()
    logging.info("Bot stopped.")

def run():
    asyncio.run(start_bot())
