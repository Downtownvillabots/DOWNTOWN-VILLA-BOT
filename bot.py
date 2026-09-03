import asyncio
import logging

from pyrogram import idle, __version__, filters
from pyrogram.raw.all import layer
from pyrogram.types import Message

from config import validate_config, BOT_NAME
from core.logging import setup_logging
from downtownvilla.Bot import downtownvilla
from utils import temp
from Script import script

setup_logging()
logger = logging.getLogger(__name__)

@downtownvilla.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    await message.reply_text(
        script.START_TEXT.format(message.from_user.first_name, BOT_NAME),
        parse_mode="HTML"
    )
    logger.info("User %s started", message.from_user.id)

async def main():
    validate_config()
    logger.info("Config validated ✅")

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
