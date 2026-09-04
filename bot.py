import speed_boost

import asyncio
import logging

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

# ------------------------------------------------------------
# UNIVERSAL DEBUG HANDLER – logs EVERY update
# ------------------------------------------------------------
@downtownvilla.on_message(filters.private)
async def debug_all_private(client, message: Message):
    print(f"🔥 DEBUG: Got private message from {message.from_user.id}: {message.text if message.text else 'non-text'}")
    if message.text == "/start":
        await message.reply_text(
            script.START_TEXT.format(message.from_user.first_name, BOT_NAME),
            parse_mode="HTML"
        )
        print("✅ START RESPONDED")
    else:
        await message.reply_text("I received your message! (Debug bot)")

# ------------------------------------------------------------
# Background task to print "still running" every 10 seconds
# ------------------------------------------------------------
async def heartbeat():
    while True:
        print("💓 Bot is alive, waiting for updates...")
        await asyncio.sleep(10)

async def main():
    print("🚀 bot.py started")
    validate_config()
    logger.info("Config validated ✅")

    await start_web_server()

    logger.info("Starting DOWNTOWN VILLA BOT...")
    await downtownvilla.start()

    # Start heartbeat
    asyncio.create_task(heartbeat())

    me = await downtownvilla.get_me()
    temp.ME = me.id
    temp.U_NAME = me.username
    temp.B_NAME = me.first_name
    logger.info(f"Bot started as {me.first_name} (Pyrogram v{__version__})")
    print(script.LOGO)

    # Send startup message to owner
    try:
        if OWNER_IDS:
            owner_id = OWNER_IDS[0]
            await downtownvilla.send_message(
                owner_id,
                "✅ Bot is online. Debug mode enabled."
            )
            print("✅ Sent startup PM to owner")
    except Exception as e:
        print(f"❌ Startup PM error: {e}")

    await idle()

if __name__ == "__main__":
    asyncio.run(main())
