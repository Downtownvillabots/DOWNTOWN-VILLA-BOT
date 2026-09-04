import speed_boost

import asyncio
import logging
import os

from pyrogram import idle, __version__, filters
from pyrogram.types import Message
from aiohttp import web

from config import validate_config, PORT, BOT_NAME, OWNER_IDS
from core.logging import setup_logging
from downtownvilla.Bot import downtownvilla
from utils import temp
from Script import script

setup_logging()
logger = logging.getLogger(__name__)

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

# ---- DEBUG: /ping command (direct on client) ----
@downtownvilla.on_message(filters.command("ping") & filters.private)
async def ping_command(client, message: Message):
    await message.reply_text("Pong! 🏓")
    print(f"PING RECEIVED from {message.from_user.id}")

# ---- DEBUG: /start command (fallback) ----
@downtownvilla.on_message(filters.command("start") & filters.private)
async def fallback_start(client, message: Message):
    await message.reply_text(
        script.START_TEXT.format(message.from_user.first_name, BOT_NAME),
        parse_mode="HTML"
    )
    print(f"START RECEIVED from {message.from_user.id}")

async def main():
    print("DEBUG: bot.py is running")
    validate_config()
    logger.info("Config validated ✅")

    await start_web_server()

    logger.info("Starting DOWNTOWN VILLA BOT...")
    await downtownvilla.start()

    print("DEBUG: Client started – listening for updates")

    # Send a startup message to owner (to confirm bot is alive)
    try:
        if OWNER_IDS:
            owner_id = OWNER_IDS[0]
            await downtownvilla.send_message(
                owner_id,
                "✅ DOWNTOWN VILLA BOT is now online and running."
            )
            print(f"DEBUG: Sent startup notification to owner {owner_id}")
    except Exception as e:
        print(f"DEBUG: Could not send startup notification: {e}")

    me = await downtownvilla.get_me()
    temp.ME = me.id
    temp.U_NAME = me.username
    temp.B_NAME = me.first_name
    logger.info(f"Bot started as {me.first_name} (Pyrogram v{__version__})")
    print(script.LOGO)

    await idle()

if __name__ == "__main__":
    asyncio.run(main())
