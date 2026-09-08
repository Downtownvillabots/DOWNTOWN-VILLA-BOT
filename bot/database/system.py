"""
System database service.

Provides a high-level API for the bot's internal database:
- Settings, cache, temporary data, etc.
"""

import logging
from typing import Any, Dict, Optional

from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry

logger = logging.getLogger("database.system")

class SystemDatabase:
    """
    A wrapper around the system database (if configured).
    Provides methods like get, set, delete.
    """

    def __init__(self, manager: DatabaseManager, registry: DatabaseRegistry):
        self.manager = manager
        self.registry = registry
        self._db = None  # MotorDatabase

    async def initialize(self):
        """Fetch the system database object from the manager."""
        info = self.registry.get_info("system")
        if not info:
            logger.warning("System database not configured.")
            return
        self._db = self.manager.get_registered_database("system")
        if self._db is None:
            logger.error("System database not registered in manager.")
            return
        logger.info("System database initialized.")

    async def set(self, key: str, value: Any):
        """Store a value under a key in the 'settings' collection."""
        if not self._db:
            logger.warning("System database not available; cannot set %s.", key)
            return
        collection = self._db["settings"]
        await collection.update_one(
            {"key": key},
            {"$set": {"value": value}},
            upsert=True
        )
        logger.debug("Set system setting '%s'.", key)

    async def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value for a key, or return default."""
        if not self._db:
            logger.warning("System database not available; cannot get %s.", key)
            return default
        collection = self._db["settings"]
        doc = await collection.find_one({"key": key})
        if doc and "value" in doc:
            return doc["value"]
        return default

    async def delete(self, key: str):
        """Delete a setting."""
        if not self._db:
            logger.warning("System database not available; cannot delete %s.", key)
            return
        collection = self._db["settings"]
        await collection.delete_one({"key": key})
        logger.debug("Deleted system setting '%s'.", key)

    async def close(self):
        """Not needed here; manager closes clients."""
        pass
