from pyrogram import Client, filters
from pyrogram.types import Message
from datetime import datetime
from database.core.users import UserRepository
from database.core.groups import GroupRepository
from core.config import ADMINS

user_repo = UserRepository()
group_repo = GroupRepository()

@Client.on_message(filters.command("start") & filters.private)
async def start_private(client: Client, message: Message):
    user_id = message.from_user.id
    now = datetime.utcnow()

    # Register/update user
    await user_repo.create_or_update_user(user_id, {
        "user_id": user_id,
        "first_name": message.from_user.first_name,
        "username": message.from_user.username,
        "last_seen": now,
    })

    await message.reply_text(
        "✅ **DOWNTOWN VILLA BOT** is running.\n\n"
        "You are now registered in our database.\n"
        "Features will be added soon."
    )

@Client.on_message(filters.new_chat_members)
async def bot_added_to_group(client: Client, message: Message):
    # Check if the bot itself was added
    for member in message.new_chat_members:
        if member.id == client.me.id:
            group_id = message.chat.id
            await group_repo.create_or_update_group(group_id, {
                "group_id": group_id,
                "title": message.chat.title,
                "added_at": datetime.utcnow(),
            })
            await message.reply_text("Thank you for adding me to this group!")
            break

@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats_command(client: Client, message: Message):
    user_count = await user_repo.get_user_count()
    group_count = await group_repo.get_group_count()
    await message.reply_text(
        f"📊 **DOWNTOWN VILLA STATS**\n\n"
        f"👤 Users: `{user_count}`\n"
        f"👥 Groups: `{group_count}`"
    )
