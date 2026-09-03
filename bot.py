# ============================================================
# bot.py – Main Entry Point for DOWNTOWN VILLA BOT
# Initializes configuration, logging, database, client, and loads plugins.
# ============================================================

import asyncio
import logging
import time
from datetime import date, datetime

from pyrogram import idle, __version__
from pyrogram.raw.all import layer
from pyrogram.errors import FloodWait
from aiohttp import web

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    LOG_CHANNEL,
    PORT,
    validate_config,
    DEBUG_MODE,
)
from core.logging import setup_logging
from database.connection import get_user_db, _initialize_media_pool
from dreamxbotz.Bot import dreamxbotz
from utils import temp

# Setup logging (centralized)
setup_logging()
logger = logging.getLogger(__name__)

botStartTime = time.time()

async def start_bot():
    """Start the bot and all services."""
    try:
        # Validate configuration
        validate_config()
        logger.info("✅ Configuration validated")

        # Initialize database pool
        _initialize_media_pool()
        user_db = get_user_db()
        logger.info("✅ MongoDB connections initialized")

        # Start Telegram client
        logger.info("🚀 Starting DOWNTOWN VILLA BOT")
        await dreamxbotz.start()

        # Get bot info
        me = await dreamxbotz.get_me()
        dreamxbotz.username = me.username
        logger.info(f"✅ Bot started as {me.first_name} with Pyrogram v{__version__} (Layer {layer})")

        # Load plugins automatically (Pyrogram loads all .py files in plugins/)
        # It's already done by Pyrogram, but we can log plugin count
        # We'll let Pyrogram handle it.

        # Set up background tasks
        dreamxbotz.loop.create_task(check_expired_premium(dreamxbotz))

        # Start web server (streaming)
        from plugins import web_server
        app = web.AppRunner(await web_server())
        await app.setup()
        bind_address = "0.0.0.0"
        await web.TCPSite(app, bind_address, PORT).start()
        logger.info(f"✅ Web server started on port {PORT}")

        # Idle
        await idle()
    except FloodWait as e:
        logger.info(f"FloodWait! Sleeping for {e.value} seconds.")
        time.sleep(e.value)
    except Exception as e:
        logger.critical(f"❌ Fatal error during startup: {e}")
        raise

async def check_expired_premium(client):
    """Background task to clean expired premium users."""
    from database.users import check_expired_premium as clean_premium
    while True:
        try:
            await clean_premium()
            logger.info("[PREMIUM] Cleaned expired premium users")
        except Exception as e:
            logger.error(f"[PREMIUM] Cleanup error: {e}")
        await asyncio.sleep(3600)  # every hour

if __name__ == "__main__":
    asyncio.run(start_bot())