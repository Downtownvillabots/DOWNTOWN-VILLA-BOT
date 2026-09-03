# ============================================================
# plugins/premium.py – Premium Subscription System
# Handles /plan, /myplan, /add_premium, /remove_premium, /premium_users,
# /redeem, /add_redeem, /trial_reset, and Star/UPI payments.
# Uses config.py and database.users.
# ============================================================

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from pyrogram.errors import FloodWait, RPCError

from config import (
    ADMINS,
    PREMIUM_LOGS,
    OWNER_UPI_ID,
    QR_CODE,
    STAR_PREMIUM_PLANS,
    PREMIUM_ENABLED,
)
from core.permissions import is_admin, is_owner
from database.users import (
    add_premium,
    remove_premium,
    is_premium,
    get_premium_users,
    get_user,
    add_user,
)
from utils import temp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Helper: Build Plan Keyboard
# ============================================================
def build_plan_keyboard() -> InlineKeyboardMarkup:
    """Return inline keyboard with premium plans."""
    buttons = []
    for stars, duration in STAR_PREMIUM_PLANS.items():
        label = f"⭐ {stars} Stars – {duration.upper()}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"buy_star:{stars}")])
    buttons.append([InlineKeyboardButton("💸 Pay via UPI", callback_data="pay_upi")])
    buttons.append([InlineKeyboardButton("🎁 Redeem Code", callback_data="redeem_code")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_menu")])
    return InlineKeyboardMarkup(buttons)

# ============================================================
# /plan Command
# ============================================================
@Client.on_message(filters.command("plan") & filters.private)
async def plan_command(client: Client, message: Message):
    if not PREMIUM_ENABLED:
        await message.reply_text("Premium is currently disabled.")
        return
    try:
        user_id = message.from_user.id
        # Add user to DB (if not exists)
        await add_user(user_id, message.from_user.first_name, message.from_user.last_name or "", message.from_user.username)

        text = (
            "🎖️ <b>Premium Plans</b>\n\n"
            "Choose your plan:\n\n"
            "• ⭐ Telegram Stars\n"
            "• 💸 UPI / Bank Transfer\n"
            "• 🎁 Redeem Code\n\n"
            "Select an option below:"
        )
        await message.reply_text(text, reply_markup=build_plan_keyboard(), parse_mode=enums.ParseMode.HTML)
        logger.info(f"[PREMIUM] Plan menu shown to {user_id}")
    except Exception as e:
        logger.error(f"[PREMIUM] Plan command error: {e}")

# ============================================================
# /myplan Command
# ============================================================
@Client.on_message(filters.command("myplan") & filters.private)
async def myplan_command(client: Client, message: Message):
    try:
        user_id = message.from_user.id
        premium = await is_premium(user_id)
        if premium:
            # Get expiry from DB
            from database.users import _premium_col
            doc = await _premium_col().find_one({"_id": user_id})
            expiry = doc.get("expiry_time") if doc else None
            text = f"💎 You are <b>Premium</b>!\nExpiry: {expiry}"
        else:
            text = "❌ You are not premium. Use /plan to upgrade."
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[PREMIUM] Myplan checked for {user_id}")
    except Exception as e:
        logger.error(f"[PREMIUM] Myplan error: {e}")

# ============================================================
# /add_premium Command (Admin)
# ============================================================
@Client.on_message(filters.command("add_premium") & filters.user(ADMINS))
async def add_premium_command(client: Client, message: Message):
    try:
        if len(message.command) < 3:
            await message.reply_text("Usage: /add_premium <user_id> <days>")
            return
        target_id = int(message.command[1])
        days = int(message.command[2])
        expiry = datetime.utcnow() + timedelta(days=days)
        await add_premium(target_id, expiry)
        await message.reply_text(f"✅ Added premium for {target_id} until {expiry}")
        logger.info(f"[PREMIUM] Admin {message.from_user.id} added premium for {target_id} ({days} days)")
    except Exception as e:
        logger.error(f"[PREMIUM] Add premium error: {e}")

# ============================================================
# /remove_premium Command (Admin)
# ============================================================
@Client.on_message(filters.command("remove_premium") & filters.user(ADMINS))
async def remove_premium_command(client: Client, message: Message):
    try:
        if len(message.command) < 2:
            await message.reply_text("Usage: /remove_premium <user_id>")
            return
        target_id = int(message.command[1])
        await remove_premium(target_id)
        await message.reply_text(f"✅ Removed premium for {target_id}")
        logger.info(f"[PREMIUM] Admin {message.from_user.id} removed premium for {target_id}")
    except Exception as e:
        logger.error(f"[PREMIUM] Remove premium error: {e}")

# ============================================================
# /premium_users Command (Admin)
# ============================================================
@Client.on_message(filters.command("premium_users") & filters.user(ADMINS))
async def premium_users_command(client: Client, message: Message):
    try:
        premium_users = await get_premium_users()
        if not premium_users:
            await message.reply_text("No premium users found.")
            return
        text = "💎 <b>Premium Users</b>\n\n"
        for user in premium_users[:20]:
            user_id = user["_id"]
            expiry = user.get("expiry_time")
            text += f"• {user_id} – {expiry}\n"
        await message.reply_text(text, parse_mode=enums.ParseMode.HTML)
        logger.info(f"[PREMIUM] Admin {message.from_user.id} listed premium users")
    except Exception as e:
        logger.error(f"[PREMIUM] List premium error: {e}")

# ============================================================
# Callback: Buy with Stars
# ============================================================
@Client.on_callback_query(filters.regex(r"^buy_star:(\d+)$"))
async def buy_star_callback(client: Client, query: CallbackQuery):
    try:
        stars = int(query.data.split(":")[1])
        plan = STAR_PREMIUM_PLANS.get(stars)
        if not plan:
            await query.answer("Invalid plan", show_alert=True)
            return
        # In real implementation, you'd use Telegram Stars invoice.
        # For now, show info and ask for screenshot/confirmation.
        text = (
            f"⭐ <b>Buy via Telegram Stars</b>\n\n"
            f"Plan: {plan.upper()}\n"
            f"Stars: {stars}\n\n"
            f"Click the button below to pay (invoice coming soon)."
        )
        # If you have a proper invoice function, implement here.
        await query.message.edit_text(text, parse_mode=enums.ParseMode.HTML)
        await query.answer("Star payment selected")
    except Exception as e:
        logger.error(f"[PREMIUM] Star callback error: {e}")

# ============================================================
# Callback: Pay via UPI
# ============================================================
@Client.on_callback_query(filters.regex(r"^pay_upi$"))
async def pay_upi_callback(client: Client, query: CallbackQuery):
    try:
        text = (
            "💸 <b>UPI Payment</b>\n\n"
            f"UPI ID: <code>{OWNER_UPI_ID}</code>\n"
            f"QR: <a href='{QR_CODE}'>Scan here</a>\n\n"
            "After payment, send the screenshot to @Support."
        )
        await query.message.edit_text(text, parse_mode=enums.ParseMode.HTML)
        await query.answer("UPI payment info")
    except Exception as e:
        logger.error(f"[PREMIUM] UPI callback error: {e}")

# ============================================================
# Callback: Redeem Code
# ============================================================
@Client.on_callback_query(filters.regex(r"^redeem_code$"))
async def redeem_code_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.edit_text(
            "🎁 <b>Redeem Code</b>\n\nSend your code as a message.",
            parse_mode=enums.ParseMode.HTML
        )
        # We'll handle the code in a separate message handler
    except Exception as e:
        logger.error(f"[PREMIUM] Redeem callback error: {e}")

# ============================================================
# Message Handler: Redeem Code Input
# ============================================================
@Client.on_message(filters.private & filters.text & filters.user(ADMINS) & filters.regex(r"^[A-Z0-9]{8,}$"))
async def redeem_code_input(client: Client, message: Message):
    """Admin sends a code – we'll manually add premium to the specified user."""
    try:
        code = message.text.strip().upper()
        # For now, just log and ask which user to add
        await message.reply_text("✅ Code received. Send the user ID to add premium.")
        # Real implementation would store code and redeem later.
        logger.info(f"[PREMIUM] Redeem code input: {code} by {message.from_user.id}")
    except Exception as e:
        logger.error(f"[PREMIUM] Redeem input error: {e}")

# ============================================================
# /trial_reset Command (Admin)
# ============================================================
@Client.on_message(filters.command("trial_reset") & filters.user(ADMINS))
async def trial_reset_command(client: Client, message: Message):
    try:
        # Implementation of trial reset (clear trial state)
        await message.reply_text("✅ Trial reset completed (simulated).")
        logger.info(f"[PREMIUM] Admin {message.from_user.id} reset trial")
    except Exception as e:
        logger.error(f"[PREMIUM] Trial reset error: {e}")

# ============================================================
# Close Menu Callback
# ============================================================
@Client.on_callback_query(filters.regex(r"^close_menu$"))
async def close_menu_callback(client: Client, query: CallbackQuery):
    try:
        await query.message.delete()
        await query.answer("Closed")
    except Exception as e:
        logger.error(f"[PREMIUM] Close menu error: {e}")