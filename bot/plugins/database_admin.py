# bot/plugins/database_admin.py
"""
Admin /database command – fully self-contained plugin.
"""

import logging
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.core.helpers import human_readable_size
from bot.core.permissions import Permissions
from bot.database import db_manager, db_registry, db_analytics

logger = logging.getLogger("plugins.database_admin")

# ---------- UI Helper Functions ----------
async def show_overview(client, message_or_query, edit=False):
    totals = await db_analytics.get_total_stats()
    user_totals = await db_analytics.get_total_stats("user")
    file_totals = await db_analytics.get_total_stats("file")

    text = (
        "📊 **DATABASE CONTROL CENTER**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Total databases: {len(db_registry.get_all())}\n"
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
    for info in db_registry.get_all():
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
    info = db_registry.get_info(key)
    if not info:
        await callback_query.answer("Unknown database.", show_alert=True)
        return
    stats = await db_analytics.get_database_stats(key)

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
    totals = await db_analytics.get_total_stats()
    user_totals = await db_analytics.get_total_stats("user")
    file_totals = await db_analytics.get_total_stats("file")

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
    await db_registry.update_all_stats()
    await show_overview(client, callback_query, edit=True)

# ---------- Handlers ----------
async def database_command(client: Client, message: Message):
    # Log every message to confirm handler is called
    logger.info("database_admin handler triggered for: %s", message.text)
    if not message.text or not message.text.lower().startswith("/database"):
        return
    logger.info("Received /database from %s (id=%d)", message.from_user.first_name, message.from_user.id)
    if not Permissions.is_privileged(message.from_user.id):
        await message.reply_text("❌ You do not have permission.")
        return
    await show_overview(client, message)

async def database_callback(client: Client, callback_query: CallbackQuery):
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

# ---------- Plugin Setup ----------
def setup(app: Client):
    logger.info("Setting up database_admin plugin...")

    # Register handler for ALL messages (we filter manually)
    @app.on_message(filters.all)
    async def message_handler(client, message):
        await database_command(client, message)

    # Register callback handler for inline buttons
    @app.on_callback_query(filters.regex(r"^db:"))
    async def callback_handler(client, callback_query):
        await database_callback(client, callback_query)

    logger.info("database_admin plugin setup complete.")
