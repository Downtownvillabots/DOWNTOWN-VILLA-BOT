# ============================================================
# plugins/indexing.py – File Indexing System
# Handles indexing files from channels/groups, with progress tracking.
# Uses database.files.save_file() and validates admin permissions.
# ============================================================

import logging
import asyncio
import re
import time
from datetime import datetime
from typing import Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import FloodWait, ChatAdminRequired, RPCError

from config import (
    ADMINS,
    INDEX_REQ_CHANNEL,
    LOG_CHANNEL,
)
from core.permissions import is_admin
from database.files import save_file
from utils import temp, get_readable_time

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

lock = asyncio.Lock()

# ============================================================
# Index Button Callback
# ============================================================
@Client.on_callback_query(filters.regex(r"^index"))
async def index_files_callback(client: Client, query):
    try:
        if query.data.startswith("index_cancel"):
            temp.CANCEL = True
            await query.answer("Cancelling Indexing")
            return

        _, raju, chat, lst_msg_id, from_user = query.data.split("#")
        if raju == "reject":
            await query.message.delete()
            await client.send_message(int(from_user), "Your submission for indexing has been declined.")
            return

        if lock.locked():
            await query.answer("Wait until previous process completes.", show_alert=True)
            return

        if not is_admin(int(from_user)):
            await query.answer("❌ Admin only", show_alert=True)
            return

        await query.answer("Processing...⏳", show_alert=True)
        await query.message.edit_text("Starting Indexing", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="index_cancel")]]))

        try:
            chat = int(chat)
        except ValueError:
            pass

        await index_files_to_db(int(lst_msg_id), chat, query.message, client)
    except Exception as e:
        logger.error(f"[INDEX] Callback error: {e}")

# ============================================================
# Forwarded / Link Message Handler (for indexing)
# ============================================================
@Client.on_message((filters.forwarded | (filters.regex(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")) & filters.text ) & filters.private & filters.incoming)
async def send_for_index(client: Client, message: Message):
    if message.text:
        regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(message.text)
        if not match:
            return
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int("-100" + chat_id)
    elif message.forward_from_chat and message.forward_from_chat.type == enums.ChatType.CHANNEL:
        last_msg_id = message.forward_from_message_id
        chat_id = message.forward_from_chat.username or message.forward_from_chat.id
    else:
        return

    try:
        await client.get_chat(chat_id)
    except:
        return await message.reply("Invalid chat.")

    if message.from_user.id in ADMINS:
        buttons = [
            [InlineKeyboardButton("Yes", callback_data=f"index#accept#{chat_id}#{last_msg_id}#{message.from_user.id}")],
            [InlineKeyboardButton("Close", callback_data="close_data")]
        ]
        return await message.reply(
            f"Do you want to index this channel?\nChat: <code>{chat_id}</code>\nLast Message: <code>{last_msg_id}</code>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=enums.ParseMode.HTML
        )

    # Non‑admin: send to request channel
    try:
        await client.send_message(INDEX_REQ_CHANNEL, f"#IndexRequest\n\nBy: {message.from_user.mention}\nChat: {chat_id}\nLast: {last_msg_id}")
    except Exception as e:
        logger.error(f"[INDEX] Request channel error: {e}")

# ============================================================
# Indexing Function (Core)
# ============================================================
async def index_files_to_db(lst_msg_id: int, chat: int, msg: Message, client: Client):
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    BATCH_SIZE = 200
    start_time = time.time()

    async with lock:
        try:
            current = temp.CURRENT
            temp.CANCEL = False
            total_messages = lst_msg_id
            total_fetch = lst_msg_id - current

            if total_messages <= 0:
                await msg.edit("No messages to index.")
                return

            await msg.edit(
                f"Indexing Starting...\nTotal: {total_messages}\nFetched: {total_fetch}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="index_cancel")]])
            )

            while current < total_messages:
                if temp.CANCEL:
                    break

                batch_start = current + 1
                batch_end = min(current + BATCH_SIZE, total_messages)
                message_ids = range(batch_start, batch_end + 1)

                try:
                    messages = await client.get_messages(chat, list(message_ids))
                    if not isinstance(messages, list):
                        messages = [messages]
                except Exception as e:
                    logger.error(f"[INDEX] Fetch error: {e}")
                    current = batch_end
                    continue

                save_tasks = []
                for message in messages:
                    current += 1
                    try:
                        if message.empty:
                            deleted += 1
                            continue
                        elif not message.media:
                            no_media += 1
                            continue
                        elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.AUDIO, enums.MessageMediaType.DOCUMENT]:
                            unsupported += 1
                            continue

                        media = getattr(message, message.media.value, None)
                        if not media:
                            unsupported += 1
                            continue

                        media.file_type = message.media.value
                        media.caption = message.caption
                        save_tasks.append(save_file(media))
                    except Exception as e:
                        logger.error(f"[INDEX] Loop error: {e}")
                        errors += 1
                        continue

                results = await asyncio.gather(*save_tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        errors += 1
                    else:
                        ok, code = result
                        if ok:
                            total_files += 1
                        elif code == 0:
                            duplicate += 1
                        elif code == 2:
                            errors += 1

                elapsed = time.time() - start_time
                progress = current - temp.CURRENT
                percentage = (progress / total_fetch) * 100 if total_fetch else 0
                await msg.edit(
                    f"Indexing Progress...\n"
                    f"Total: {total_messages}\nFetched: {current}\n"
                    f"Saved: {total_files} | Duplicates: {duplicate} | Errors: {errors}\n"
                    f"Progress: {percentage:.1f}%\nElapsed: {get_readable_time(elapsed)}",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="index_cancel")]])
                )
                logger.info(f"[INDEX] Progress: {current}/{total_messages} – {percentage:.1f}%")

            elapsed = time.time() - start_time
            await msg.edit(
                f"✅ Indexing Completed!\n"
                f"Total Messages: {total_messages}\n"
                f"Fetched: {current}\n"
                f"Saved: {total_files} | Duplicates: {duplicate} | Errors: {errors}\n"
                f"Elapsed: {get_readable_time(elapsed)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Close", callback_data="close_data")]])
            )
            logger.info(f"[INDEX] Completed for chat {chat} – Saved {total_files}, Dup {duplicate}, Err {errors}")

        except Exception as e:
            logger.error(f"[INDEX] Fatal error: {e}")
            await msg.edit(f"❌ Error: <code>{e}</code>", parse_mode=enums.ParseMode.HTML)

# ============================================================
# Close Data Callback
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_data$"))
async def close_data(client: Client, query):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[INDEX] Close error: {e}")