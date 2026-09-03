# ============================================================
# plugins/verification.py – Verification System
# Handles 3-step verification using shorteners, tutorials, and premium bypass.
# ============================================================

import logging
import asyncio
import time
from datetime import datetime
from typing import Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import FloodWait, RPCError

from config import (
    ADMINS,
    IS_VERIFY,
    LOG_VR_CHANNEL,
    TWO_VERIFY_GAP,
    THREE_VERIFY_GAP,
    TUTORIAL,
    TUTORIAL_2,
    TUTORIAL_3,
    SHORTENER_API,
    SHORTENER_WEBSITE,
    VERIFY_IMG,
)
from core.permissions import is_admin
from database.users import (
    get_user,
    is_premium,
    set_verify_status,
    get_verify_status,
    reset_verification,
)
from database.connection import get_user_db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Verification Status Constants
# ============================================================
VERIFY_1 = 1
VERIFY_2 = 2
VERIFY_3 = 3

# ============================================================
# Helper: Check if verification is needed for user
# ============================================================
async def needs_verification(user_id: int) -> bool:
    """Return True if user needs verification (not premium, verification enabled)."""
    if not IS_VERIFY:
        return False
    # Premium users bypass verification
    if await is_premium(user_id):
        return False
    # Admins bypass verification
    if is_admin(user_id):
        return False
    return True

# ============================================================
# Helper: Generate shortlink
# ============================================================
async def get_shortlink(url: str) -> str:
    """Create a shortlink using SHORTENER_API / SHORTENER_WEBSITE."""
    if not SHORTENER_API or not SHORTENER_WEBSITE:
        # Return original URL if no shortener configured
        return url
    try:
        import shortzy
        s = shortzy.Shortzy(api_key=SHORTENER_API, base_site=SHORTENER_WEBSITE)
        return await s.short(url)
    except Exception as e:
        logger.error(f"[VERIFY] Shortener error: {e}")
        return url

# ============================================================
# Verification Button Handler (on message)
# ============================================================
@Client.on_message(filters.private & ~filters.user(ADMINS) & ~filters.bot)
async def verify_handler(client: Client, message: Message):
    if not IS_VERIFY:
        return
    try:
        user_id = message.from_user.id
        # Skip premium users
        if await is_premium(user_id):
            return

        # Check verification status
        verify_doc = await get_verify_status(user_id)
        current_stage = verify_doc.get("stage", 0) if verify_doc else 0

        # If not verified yet, prompt with buttons
        if current_stage == 0:
            await message.reply_text(
                "👋 Hey {},\n\nYou need to verify to continue.\n\n"
                "Click the button below to verify.".format(message.from_user.first_name),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ VERIFY", callback_data="verify_start")],
                    [InlineKeyboardButton("💎 GET PREMIUM", callback_data="verify_premium")],
                ]),
                parse_mode=enums.ParseMode.HTML
            )
            return

        # If verified, check if time gap exceeded (re-verify)
        if verify_doc and verify_doc.get("timestamp"):
            last_verify = verify_doc["timestamp"]
            if current_stage == 1:
                gap = TWO_VERIFY_GAP
            elif current_stage == 2:
                gap = THREE_VERIFY_GAP
            else:
                gap = 0

            if time.time() - last_verify > gap and gap > 0:
                # Force re-verification
                await reset_verification(user_id)
                await message.reply_text("Verification expired. Please verify again.")
                # Re-prompt
                await verify_handler(client, message)
                return

    except Exception as e:
        logger.error(f"[VERIFY] Handler error: {e}")

# ============================================================
# Callback: Start Verification
# ============================================================
@Client.on_callback_query(filters.regex(r"^verify_start$"))
async def verify_start_callback(client: Client, query: CallbackQuery):
    try:
        user_id = query.from_user.id
        # Create verification link with shortener
        # First verification
        verify_url = f"https://t.me/{client.me.username}?start=verify_1_{user_id}"
        short_url = await get_shortlink(verify_url)
        await query.message.edit_text(
            "🔐 **Verification Step 1/3**\n\n"
            f"Click the link below:\n{short_url}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 VERIFY", url=short_url)],
                [InlineKeyboardButton("❌ CANCEL", callback_data="verify_cancel")],
            ]),
            parse_mode=enums.ParseMode.HTML
        )
        await query.answer("Verification link sent")
    except Exception as e:
        logger.error(f"[VERIFY] Start callback error: {e}")

# ============================================================
# Callback: Premium Button
# ============================================================
@Client.on_callback_query(filters.regex(r"^verify_premium$"))
async def verify_premium_callback(client: Client, query: CallbackQuery):
    try:
        text = (
            "💎 **Premium** bypasses verification.\n\n"
            "Use /plan to upgrade."
        )
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 VIEW PLANS", callback_data="buy_star:40")],
            [InlineKeyboardButton("❌ CLOSE", callback_data="close_menu")],
        ]), parse_mode=enums.ParseMode.HTML)
        await query.answer("Premium info shown")
    except Exception as e:
        logger.error(f"[VERIFY] Premium callback error: {e}")

# ============================================================
# Callback: Cancel Verification
# ============================================================
@Client.on_callback_query(filters.regex(r"^verify_cancel$"))
async def verify_cancel_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
        await query.answer("Verification cancelled")
    except Exception as e:
        logger.error(f"[VERIFY] Cancel error: {e}")

# ============================================================
# Handle /start with verify token (e.g., /start verify_1_123)
# ============================================================
@Client.on_message(filters.command("start") & filters.private)
async def verify_start_command(client: Client, message: Message):
    if not IS_VERIFY:
        return
    try:
        if len(message.command) > 1:
            arg = message.command[1]
            if arg.startswith("verify_1_"):
                user_id = int(arg.split("_")[2])
                if user_id == message.from_user.id:
                    # Set verification stage 1
                    await set_verify_status(user_id, VERIFY_1)
                    # Send second verification prompt
                    verify_url_2 = f"https://t.me/{client.me.username}?start=verify_2_{user_id}"
                    short_url_2 = await get_shortlink(verify_url_2)
                    await message.reply_text(
                        "✅ **Step 1 Complete!**\n\n"
                        "Now do **Step 2/3**:",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔗 VERIFY STEP 2", url=short_url_2)],
                            [InlineKeyboardButton("❌ CANCEL", callback_data="verify_cancel")],
                        ]),
                        parse_mode=enums.ParseMode.HTML
                    )
                    logger.info(f"[VERIFY] User {user_id} completed step 1")
                else:
                    await message.reply_text("❌ Invalid token.")
            elif arg.startswith("verify_2_"):
                user_id = int(arg.split("_")[2])
                if user_id == message.from_user.id:
                    await set_verify_status(user_id, VERIFY_2)
                    verify_url_3 = f"https://t.me/{client.me.username}?start=verify_3_{user_id}"
                    short_url_3 = await get_shortlink(verify_url_3)
                    await message.reply_text(
                        "✅ **Step 2 Complete!**\n\n"
                        "Now do **Step 3/3**:",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔗 VERIFY STEP 3", url=short_url_3)],
                            [InlineKeyboardButton("❌ CANCEL", callback_data="verify_cancel")],
                        ]),
                        parse_mode=enums.ParseMode.HTML
                    )
                    logger.info(f"[VERIFY] User {user_id} completed step 2")
                else:
                    await message.reply_text("❌ Invalid token.")
            elif arg.startswith("verify_3_"):
                user_id = int(arg.split("_")[2])
                if user_id == message.from_user.id:
                    await set_verify_status(user_id, VERIFY_3)
                    await message.reply_text(
                        "🎉 **Verification Complete!**\n\n"
                        "You now have full access."
                    )
                    # Send success to log channel
                    if LOG_VR_CHANNEL:
                        await client.send_message(
                            LOG_VR_CHANNEL,
                            f"✅ Verified: {user_id} @ {message.from_user.username or 'N/A'}"
                        )
                    logger.info(f"[VERIFY] User {user_id} completed verification")
                else:
                    await message.reply_text("❌ Invalid token.")
    except Exception as e:
        logger.error(f"[VERIFY] Start command error: {e}")

# ============================================================
# Close Menu Callback
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[VERIFY] Close error: {e}")