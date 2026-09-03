# ============================================================
# plugins/broadcast.py – Standard Broadcast System
# Handles /broadcast, /grp_broadcast, /send commands.
# Uses config.py, core.permissions, database.users.
# ============================================================

import logging
import asyncio
import time
from datetime import datetime
from typing import Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import FloodWait, RPCError, UserIsBlocked, InputUserDeactivated

from config import (
    ADMINS,
    BROADCAST_MAX_CONCURRENT,
    BROADCAST_RETRY_COUNT,
    BROADCAST_DELAY,
)
from core.permissions import is_admin
from database.users import get_all_users, get_all_groups, get_user

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Helper: Get eligible users/groups
# ============================================================
async def get_eligible_users():
    """Return list of user IDs from database."""
    users = await get_all_users()
    return [user["_id"] for user in users if user.get("_id")]

async def get_eligible_groups():
    """Return list of group IDs from database."""
    groups = await get_all_groups()
    return [group["_id"] for group in groups if group.get("_id")]

# ============================================================
# /broadcast Command (Admin)
# ============================================================
@Client.on_message(filters.command("broadcast") & filters.user(ADMINS))
async def broadcast_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Usage: /broadcast <message> (or reply to a message)")
        return
    try:
        # Get the message to broadcast (either command text or replied message)
        if message.reply_to_message:
            target_msg = message.reply_to_message
        else:
            target_msg = message

        # Confirm with admin
        confirm_text = (
            "📢 **Broadcast Confirmation**\n\n"
            "Are you sure you want to send this message to all users?\n\n"
            "This may take time."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ YES", callback_data="confirm_broadcast"),
             InlineKeyboardButton("❌ NO", callback_data="cancel_broadcast")],
        ])
        sent_confirm = await message.reply_text(confirm_text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

        # Store the target message for later use
        # We'll store in a temporary dict
        temp.BROADCAST_MSG = target_msg
        temp.BROADCAST_TYPE = "users"
        temp.BROADCAST_CONFIRM_ID = sent_confirm.id

        logger.info(f"[BROADCAST] Admin {message.from_user.id} initiated broadcast to users")

    except Exception as e:
        logger.error(f"[BROADCAST] Command error: {e}")

# ============================================================
# /grp_broadcast Command (Admin)
# ============================================================
@Client.on_message(filters.command("grp_broadcast") & filters.user(ADMINS))
async def grp_broadcast_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Usage: /grp_broadcast <message> (or reply to a message)")
        return
    try:
        if message.reply_to_message:
            target_msg = message.reply_to_message
        else:
            target_msg = message

        confirm_text = (
            "📢 **Group Broadcast Confirmation**\n\n"
            "Are you sure you want to send this message to all connected groups?\n\n"
            "This may take time."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ YES", callback_data="confirm_grp_broadcast"),
             InlineKeyboardButton("❌ NO", callback_data="cancel_broadcast")],
        ])
        sent_confirm = await message.reply_text(confirm_text, reply_markup=keyboard, parse_mode=enums.ParseMode.HTML)

        temp.BROADCAST_MSG = target_msg
        temp.BROADCAST_TYPE = "groups"
        temp.BROADCAST_CONFIRM_ID = sent_confirm.id

        logger.info(f"[BROADCAST] Admin {message.from_user.id} initiated group broadcast")

    except Exception as e:
        logger.error(f"[BROADCAST] Group command error: {e}")

# ============================================================
# /send Command (Admin)
# ============================================================
@Client.on_message(filters.command("send") & filters.user(ADMINS))
async def send_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ Usage: /send <user_id> <message> (or reply)")
        return
    try:
        target_id = int(message.command[1])
        if message.reply_to_message:
            target_msg = message.reply_to_message
        else:
            target_msg = message

        # Send the message
        await client.copy_message(
            target_id,
            message.chat.id,
            target_msg.id,
            reply_markup=target_msg.reply_markup,
            caption=target_msg.caption,
            parse_mode=enums.ParseMode.HTML
        )
        await message.reply_text(f"✅ Sent to {target_id}")
        logger.info(f"[BROADCAST] Admin {message.from_user.id} sent message to {target_id}")
    except Exception as e:
        logger.error(f"[BROADCAST] Send error: {e}")
        await message.reply_text(f"❌ Error: {e}")

# ============================================================
# Confirmation Callbacks
# ============================================================
@Client.on_callback_query(filters.regex(r"^confirm_broadcast$"))
async def confirm_broadcast_callback(client: Client, query):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        target_msg = getattr(temp, "BROADCAST_MSG", None)
        if not target_msg:
            await query.answer("No broadcast message found", show_alert=True)
            return

        # Delete confirmation message
        await query.message.delete()
        await query.answer("Broadcasting...", show_alert=False)

        # Start broadcast task
        asyncio.create_task(execute_broadcast(client, target_msg, "users", query.from_user.id))
        logger.info(f"[BROADCAST] Started user broadcast by {query.from_user.id}")

    except Exception as e:
        logger.error(f"[BROADCAST] Confirm error: {e}")

@Client.on_callback_query(filters.regex(r"^confirm_grp_broadcast$"))
async def confirm_grp_broadcast_callback(client: Client, query):
    if not is_admin(query.from_user.id):
        await query.answer("❌ Admin only", show_alert=True)
        return
    try:
        target_msg = getattr(temp, "BROADCAST_MSG", None)
        if not target_msg:
            await query.answer("No broadcast message found", show_alert=True)
            return

        await query.message.delete()
        await query.answer("Broadcasting...", show_alert=False)

        asyncio.create_task(execute_broadcast(client, target_msg, "groups", query.from_user.id))
        logger.info(f"[BROADCAST] Started group broadcast by {query.from_user.id}")

    except Exception as e:
        logger.error(f"[BROADCAST] Group confirm error: {e}")

@Client.on_callback_query(filters.regex(r"^cancel_broadcast$"))
async def cancel_broadcast_callback(client: Client, query):
    await query.message.delete()
    await query.answer("Broadcast cancelled")

# ============================================================
# Execute Broadcast
# ============================================================
async def execute_broadcast(client: Client, target_msg, target_type: str, admin_id: int):
    """Actual broadcast executor."""
    try:
        # Get target list
        if target_type == "users":
            targets = await get_eligible_users()
        elif target_type == "groups":
            targets = await get_eligible_groups()
        else:
            targets = []

        total = len(targets)
        success = 0
        failed = 0
        start_time = time.time()

        # Notify admin
        status_msg = await client.send_message(
            admin_id,
            f"📢 Broadcasting started to {total} {target_type}...",
            parse_mode=enums.ParseMode.HTML
        )

        # Send to each target
        semaphore = asyncio.Semaphore(BROADCAST_MAX_CONCURRENT)
        async def send_to_one(target_id):
            nonlocal success, failed
            async with semaphore:
                try:
                    await target_msg.copy(target_id)
                    success += 1
                except FloodWait as e:
                    logger.warning(f"[BROADCAST] FloodWait on {target_id}: {e.value}s")
                    await asyncio.sleep(e.value)
                    try:
                        await target_msg.copy(target_id)
                        success += 1
                    except Exception:
                        failed += 1
                except (UserIsBlocked, InputUserDeactivated):
                    failed += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"[BROADCAST] Failed to {target_id}: {e}")

        # Run batches with delay
        batch_size = 20
        for i in range(0, len(targets), batch_size):
            batch = targets[i:i+batch_size]
            await asyncio.gather(*[send_to_one(t) for t in batch])
            await asyncio.sleep(BROADCAST_DELAY)

        elapsed = time.time() - start_time
        # Update status message
        try:
            await status_msg.edit_text(
                f"✅ **Broadcast Complete**\n\n"
                f"Total: {total}\n"
                f"Success: {success}\n"
                f"Failed: {failed}\n"
                f"Time: {int(elapsed)}s",
                parse_mode=enums.ParseMode.HTML
            )
        except FloodWait as e:
            logger.warning(f"[BROADCAST] Status edit floodwait: {e.value}")
            await asyncio.sleep(e.value)
            await status_msg.edit_text("✅ Broadcast Complete")

        logger.info(f"[BROADCAST] Completed. Total {total}, Success {success}, Failed {failed}")

    except Exception as e:
        logger.exception(f"[BROADCAST] Fatal error: {e}")

# ============================================================
# Close Menu Callback
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client: Client, query):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[BROADCAST] Close error: {e}")