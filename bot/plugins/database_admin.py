# bot/plugins/database_admin.py
"""
Helper functions for database admin UI.
(Handlers are registered directly in main.py)
"""
import logging
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger("plugins.database_admin")

# These will be set from main.py
manager = None
registry = None
analytics = None

def set_globals(mgr, reg, ana):
    global manager, registry, analytics
    manager = mgr
    registry = reg
    analytics = ana

# All UI functions here (same as before)
async def show_overview(client, message_or_query, edit=False):
    # ... (full code as before)
async def show_database_detail(client, callback_query, key):
    # ... (full code as before)
async def show_totals(client, callback_query, edit=True):
    # ... (full code as before)
async def refresh_data(client, callback_query):
    # ... (full code as before)
