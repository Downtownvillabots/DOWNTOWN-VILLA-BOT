# bot/database/__init__.py
"""
Database package.

Exposes singleton instances of the manager, registry, and analytics.
Plugins can import these to access database services.
"""

from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry
from bot.database.analytics import DatabaseAnalytics
from bot.database.system import SystemDatabase
from bot.database.users import UserDatabase
from bot.database.files import FileDatabase

# Singleton instances
db_manager = DatabaseManager()
db_registry = DatabaseRegistry(db_manager)
db_analytics = DatabaseAnalytics(db_manager, db_registry)
db_system = SystemDatabase(db_manager, db_registry)
db_users = UserDatabase(db_manager, db_registry)
db_files = FileDatabase(db_manager, db_registry)

__all__ = [
    "db_manager",
    "db_registry",
    "db_analytics",
    "db_system",
    "db_users",
    "db_files",
]
