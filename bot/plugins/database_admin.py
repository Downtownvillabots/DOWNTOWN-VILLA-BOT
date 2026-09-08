# bot/plugins/database_admin.py
"""
Helper functions for database admin UI.
(Handlers are registered directly in main.py)
"""
import logging
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot.core.helpers import human_readable_size

logger = logging.getLogger("plugins.database_admin")

manager = None
registry = None
analytics = None

def set_globals(mgr, reg, ana):
    global manager, registry, analytics
    manager = mgr
    registry = reg
    analytics = ana

# ... (rest of the functions exactly as above)
