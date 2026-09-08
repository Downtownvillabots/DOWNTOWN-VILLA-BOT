"""
Main entry point.
"""
import asyncio
import logging
import re
import sys

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass

from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

from bot.config import Config, validate_required
from bot.core.logging import setup_logging
from bot.core.database import database
from bot.plugins import load_plugins
from bot.core.helpers import human_readable_size
from bot.core.permissions import Permissions

from bot.database import db_manager, db_registry, db_analytics
from bot.database.health import HealthMonitor

from bot.plugins.database_admin import show_overview, show_database_detail, show_totals, refresh_data, set_globals

set_globals(db_manager, db_registry, db_analytics)

app = None
logger = logging.getLogger("main")

async def heartbeat():
    while True:
        logging.getLogger("heartbeat").info("Bot is alive.")
        await asyncio.sleep(Config.HEARTBEAT_INTERVAL)

async def start_web_server():
    from aiohttp import web
    async def handle(request):
        return web.Response(text="OK")
    web_app = web.Application()
    web_app.router.add_get("/", handle)
    web_app.router.add_get("/health", handle)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, host=Config.HOST, port=Config.PORT)
    await site.start()
    logging.getLogger("web").info(f"Web server started on {Config.HOST}:{Config.PORT}")

def get_flood_wait(error_message: str) -> int:
    match = re.search(r"wait of (\d+) seconds", error_message)
    return int(match.group(1)) if match else 60

async def database_command_handler(client: Client, message: Message):
    logger.info("database_command_handler triggered: %s", message.text)
    if not message.text or not message.text.lower().startswith("/database"):
        return
    logger.info("Received /database from %s (id=%d)", message.from_user.first_name, message.from_user.id)
    if not Permissions.is_privileged(message.from_user.id):
        logger.warning("User %d lacks permission", message.from_user.id)
        await message.reply_text("❌ You do not have permission.")
        return
    await show_overview(client, message)

async def database_callback_handler(client: Client, callback_query: CallbackQuery):
    data = callback_query.data
    user_id = callback_query.from_user.id
    if not Permissions.is_privileged(user_id):
        await callback_query.answer("❌ Access denied.", show_alert=True)
        return
    parts = data.split(":")
    action = parts[1]
    if action == "refresh":
        await refresh_data(client, callback_query)
    elif action == "view":
        key = parts[2]
        await show_database_detail(client, callback_query, key)
    elif action == "back":
        await show_overview(client, callback_query, edit=True)
    elif action == "totals":
        await show_totals(client, callback_query, edit=True)

async def main():
    global app
    validate_required()
    setup_logging()
    logger.info("Starting Telegram bot engine...")

    # Legacy database
    await database.connect()
    if database.is_connected:
        logger.info("Legacy database connection established.")
    else:
        logger.info("Legacy database not configured; running without storage.")

    # New database system
    await db_manager.initialize()
    await db_registry.discover()
    await db_registry.update_all_stats()
    health_monitor = HealthMonitor(db_manager, db_registry)
    await health_monitor.start()

    app = Client(
        "my_bot",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.BOT_TOKEN,
        workers=Config.WORKERS,
        workdir="/tmp",
    )

    # Load plugins (basic only)
    loaded = load_plugins(app)
    logger.info(f"Loaded plugins: {loaded}")

    # Directly register database admin handlers
    app.add_handler(MessageHandler(database_command_handler, filters.text))
    app.add_handler(CallbackQueryHandler(database_callback_handler, filters.regex(r"^db:")))
    logger.info("Database admin handlers added directly.")

    await start_web_server()
    heartbeat_task = asyncio.create_task(heartbeat())

    logger.info("Starting Telegram client...")
    while True:
        try:
            await app.start()
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
            break
        except Exception as e:
            error_message = str(e)
            if "FLOOD_WAIT" in error_message:
                wait_seconds = get_flood_wait(error_message)
                logger.error(f"FLOOD_WAIT – waiting {wait_seconds} seconds before retry...")
                await asyncio.sleep(wait_seconds + 5)
            else:
                logger.error(f"Client error: {error_message}. Restarting in 10 seconds...")
                await asyncio.sleep(10)
            try:
                await app.stop()
            except Exception:
                pass
            heartbeat_task.cancel()
            heartbeat_task = asyncio.create_task(heartbeat())
            continue

    heartbeat_task.cancel()
    await health_monitor.stop()
    await db_manager.close_all()
    await database.close()
    await app.stop()
    logger.info("Bot stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logging.getLogger("main").error(f"Fatal error: {e}")
        sys.exit(1)
