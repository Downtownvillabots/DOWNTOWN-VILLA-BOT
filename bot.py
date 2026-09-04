# ============================================================
# bot.py – DOWNTOWN VILLA ULTIMATE ENGINE
# Imports speed_boost, starts bot + minimal web server.
# ============================================================

import speed_boost  # <-- apply all speed optimizations

import asyncio
import logging

from pyrogram import idle, __version__, filters
from pyrogram.types import Message
from aiohttp import web

from config import validate_config, BOT_NAME, PORT
from core.logging import setup_logging
from downtownvilla.Bot import downtownvilla
from utils import temp
from Script import script

setup_logging()
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# Minimal web server (so Render sees the port)
# ------------------------------------------------------------
async def handle_root(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Web server started on port {PORT}")

# ------------------------------------------------------------
# Basic /start command
# ------------------------------------------------------------

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
async def main():
    validate_config()
    logger.info("Config validated ✅")

    # Start web server first
    await start_web_server()

    logger.info("Starting DOWNTOWN VILLA BOT...")
    await downtownvilla.start()

    me = await downtownvilla.get_me()
    temp.ME = me.id
    temp.U_NAME = me.username
    temp.B_NAME = me.first_name
    logger.info(f"Bot started as {me.first_name} (Pyrogram v{__version__})")
    print(script.LOGO)

    await idle()

if __name__ == "__main__":
    asyncio.run(main())
