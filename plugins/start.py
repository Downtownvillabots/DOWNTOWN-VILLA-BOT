# plugins/start.py – Basic /start command
from pyrogram import Client, filters
from pyrogram.types import Message
from config import BOT_NAME
from Script import script

@Client.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    try:
        await message.reply_text(
            script.START_TEXT.format(message.from_user.first_name, BOT_NAME),
            parse_mode="HTML"
        )
        print(f"User {message.from_user.id} started")
    except Exception as e:
        print(f"ERROR in start: {e}")
