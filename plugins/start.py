from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    await message.reply_text(
        "✅ **DOWNTOWN VILLA BOT** is running.\n\n"
        "Features will be added soon."
    )
