"""
Admin /database command.

Provides a professional control center for all configured databases.
Only privileged users (owner/admin/sudo) can access.
"""

import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.handlers import MessageHandler, CallbackQueryHandler

from bot.config import Config
from bot.core.permissions import Permissions
from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry
from bot.database.analytics import DatabaseAnalytics
from bot.core.helpers import human_readable_size

logger = logging.getLogger("plugins.database_admin")

# Global references
manager: DatabaseManager = None
registry: DatabaseRegistry = None
analytics: DatabaseAnalytics = None

async def database_command(client: Client, message: Message):
    """Handle /database command."""
    logger.info("database_admin handler triggered for message: %s", message.text)
    if not message.text or not message.text.lower().startswith("/database"):
        return
    logger.info("Received /database from user %s (id=%d)", message.from_user.first_name, message.from_user.id)
    if not Permissions.is_privileged(message.from_user.id):
        logger.warning("User %d tried /database but lacks permission.", message.from_user.id)
        await message.reply_text("❌ You do not have permission to access this.")
        return
    logger.info("User %d is privileged. Showing database overview.", message.from_user.id)
    try:
        await show_overview(client, message)
    except Exception as e:
        logger.error("Database command failed: %s", e)
        await message.reply_text("⚠️ An error occurred while fetching database info.")

async def database_callback(client: Client, callback_query: CallbackQuery):
    """Handle inline button presses."""
    data = callback_query.data
    user_id = callback_query.from_user.id
    if not Permissions.is_privileged(user_id):
        await callback_query.answer("❌ Access denied.", show_alert=True)
        return

    parts = data.split(":")
    action = parts[1]
    if action == "refresh":
        await refresh_data(client, callback_query)
    elif action == "view":
        key = parts[2]
        await show_database_detail(client, callback_query, key)
    elif action == "back":
        await show_overview(client, callback_query, edit=True)
    elif action == "totals":
        await show_totals(client, callback_query, edit=True)

# Setup function (empty – we'll register handlers in main.py)
def setup(app: Client):
    pass

# ------------------------------------------------------------------
# Helper functions (UI rendering) – SAME as before
# ------------------------------------------------------------------
async def show_overview(client, message_or_query, edit=False):
    """Display the main control center."""
    totals = await analytics.get_total_stats()
    user_totals = await analytics.get_total_stats("user")
    file_totals = await analytics.get_total_stats("file")

    text = (
        "📊 **DATABASE CONTROL CENTER**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Total databases: {len(registry.get_all())}\n"
        f"📦 Total documents: {totals['documents']:,}\n"
        f"💾 Total storage: {human_readable_size(totals['storage_size'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **USER DATABASES**\n"
        f"• Count: {user_totals['databases']}\n"
        f"• Documents: {user_totals['documents']:,}\n"
        f"• Storage: {human_readable_size(user_totals['storage_size'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 **FILE DATABASES**\n"
        f"• Count: {file_totals['databases']}\n"
        f"• Documents: {file_totals['documents']:,}\n"
        f"• Storage: {human_readable_size(file_totals['storage_size'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Choose a database for details:"
    )

    buttons = []
    for info in registry.get_all():
        buttons.append([InlineKeyboardButton(
            text=f"{info.friendly_name} • {info.status}",
            callback_data=f"db:view:{info.key}"
        )])

    nav_buttons = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="db:refresh"),
         InlineKeyboardButton("📊 Totals", callback_data="db:totals")]
    ]

    reply_markup = InlineKeyboardMarkup(buttons + nav_buttons)

    if edit:
        await message_or_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await message_or_query.reply_text(text, reply_markup=reply_markup)

async def show_database_detail(client, callback_query, key):
    """Show details for a specific database."""
    info = registry.get_info(key)
    if not info:
        await callback_query.answer("Unknown database.", show_alert=True)
        return
    stats = await analytics.get_database_stats(key)

    text = (
        f"📦 **{info.friendly_name}**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗄️ Type: {info.type.upper()}\n"
        f"Status: {stats.get('status', '⚠️ UNKNOWN')}\n"
        f"Collections: {stats.get('collections', 0)}\n"
        f"Documents: {stats.get('documents', 0):,}\n"
        f"Data size: {human_readable_size(stats.get('data_size', 0))}\n"
        f"Storage size: {human_readable_size(stats.get('storage_size', 0))}\n"
        f"Index size: {human_readable_size(stats.get('index_size', 0))}\n"
        f"Total size: {human_readable_size(stats.get('total_size', 0))}\n"
        f"Avg object size: {human_readable_size(stats.get('avg_object_size', 0))}\n"
    )

    buttons = [
        [InlineKeyboardButton("⬅️ Back", callback_data="db:back"),
         InlineKeyboardButton("🔄 Refresh", callback_data=f"db:refresh")]
    ]

    await callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def show_totals(client, callback_query, edit=True):
    """Show aggregated totals."""
    totals = await analytics.get_total_stats()
    user_totals = await analytics.get_total_stats("user")
    file_totals = await analytics.get_total_stats("file")

    text = (
        "📊 **ALL DATABASES TOTAL**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗄️ Databases: {totals['databases']}\n"
        f"📦 Documents: {totals['documents']:,}\n"
        f"💾 Storage: {human_readable_size(totals['storage_size'])}\n"
        f"🧩 Indexes: {human_readable_size(totals['index_size'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 **USER DATABASES**\n"
        f"• Databases: {user_totals['databases']}\n"
        f"• Documents: {user_totals['documents']:,}\n"
        f"• Storage: {human_readable_size(user_totals['storage_size'])}\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎬 **FILE DATABASES**\n"
        f"• Databases: {file_totals['databases']}\n"
        f"• Documents: {file_totals['documents']:,}\n"
        f"• Storage: {human_readable_size(file_totals['storage_size'])}\n"
    )

    buttons = [[InlineKeyboardButton("⬅️ Back", callback_data="db:back")]]
    await callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

async def refresh_data(client, callback_query):
    """Re-fetch stats and update UI."""
    await registry.update_all_stats()
    await show_overview(client, callback_query, edit=True)
