"""
Main entry point.

Initialises the bot, loads plugins, starts the web server,
and keeps the process running.
"""

import asyncio
import logging
import sys

# Optional speed: uvloop
try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

from pyrogram import Client

from bot.config import Config, validate_required
from bot.core.logging import setup_logging
from bot.core.database import database
from bot.plugins import load_plugins

# Global app reference
app = None


async def heartbeat() -> None:
    """Print a heartbeat message every HEARTBEAT_INTERVAL seconds."""
    interval = Config.HEARTBEAT_INTERVAL
    while True:
        logging.getLogger("heartbeat").info("Bot is alive.")
        await asyncio.sleep(interval)


async def start_web_server() -> None:
    """Start a minimal aiohttp web server on the assigned port."""
    from aiohttp import web

    async def handle(request):
        return web.Response(text="OK")

    web_app = web.Application()
    web_app.router.add_get("/", handle)
    web_app.router.add_get("/health", handle)  # optional

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host=Config.HOST, port=Config.PORT)
    await site.start()
    logging.getLogger("web").info(f"Web server started on {Config.HOST}:{Config.PORT}")


async def main() -> None:
    """Main async routine."""
    global app

    # Validate required config
    validate_required()

    # Setup logging
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("Starting Telegram bot engine...")

    # Optional database connection (lazy)
    await database.connect()
    if database.is_connected:
        logger.info("Database connection established.")
    else:
        logger.info("Database not configured; running without storage.")

    # Create Pyrogram client
    app = Client(
        "my_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        workers=Config.WORKERS,
        # Speed: use tgcrypto if installed
        # Pyrogram auto‑detects and uses tgcrypto when available.
    )

    # Load plugins
    loaded = load_plugins(app)
    logger.info(f"Loaded plugins: {loaded}")

    # Start web server (for Render)
    await start_web_server()

    # Start heartbeat task
    heartbeat_task = asyncio.create_task(heartbeat())

    logger.info("Starting Telegram client...")
    try:
        # run until disconnected
        await app.start()
    except KeyboardInterrupt:
        logger.info("Stopping bot...")
    finally:
        # Cleanup
        heartbeat_task.cancel()
        await database.close()
        await app.stop()

    logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        # Catch all to keep the process alive (Render requirement)
        logging.getLogger("main").error(f"Fatal error: {e}")
        sys.exit(1)
