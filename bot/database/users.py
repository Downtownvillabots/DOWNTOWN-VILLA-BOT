"""
User database service.

Supports multiple user databases (USER_DATABASE_URI_1, _2, ...).
Provides methods to get user/group info, premium status, etc.
"""

import logging
from typing import Any, Dict, Optional, List

from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry

logger = logging.getLogger("database.users")

class UserDatabase:
    """
    High-level API for user databases.
    Allows plugins to store and retrieve user/group/channel data.
    """

    def __init__(self, manager: DatabaseManager, registry: DatabaseRegistry):
        self.manager = manager
        self.registry = registry
        self._dbs: Dict[str, Any] = {}  # key -> MotorDatabase

    async def initialize(self):
        """Fetch all user database objects from the manager."""
        for info in self.registry.get_all():
            if info.type == "user":
                db = self.manager.get_registered_database(info.key)
                if db:
                    self._dbs[info.key] = db
                    logger.info("Initialized user database '%s'.", info.friendly_name)
                else:
                    logger.error("Could not initialize user database '%s'.", info.friendly_name)

    def _get_db(self, user_id: int = None) -> Optional[Any]:
        """
        Choose the appropriate database. For simplicity, we use round-robin or hash-based.
        In production, you might want to route users to specific DBs based on ID ranges.
        We'll use a simple hash for now – consistent for the same user.
        """
        if not self._dbs:
            logger.warning("No user databases available.")
            return None
        if user_id is None:
            # if no user_id, return first DB
            key = next(iter(self._dbs))
        else:
            # hash user_id to pick a DB
            keys = sorted(self._dbs.keys())
            index = hash(user_id) % len(keys)
            key = keys[index]
        return self._dbs[key]

    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get a user document from the selected database."""
        db = self._get_db(user_id)
        if not db:
            return None
        collection = db["users"]
        doc = await collection.find_one({"user_id": user_id})
        if doc:
            logger.debug("Fetched user %d from DB.", user_id)
        return doc

    async def save_user(self, user_data: Dict):
        """Insert or update a user document."""
        user_id = user_data.get("user_id")
        if not user_id:
            logger.error("Cannot save user without user_id.")
            return
        db = self._get_db(user_id)
        if not db:
            logger.error("No user database available to save user %d.", user_id)
            return
        collection = db["users"]
        await collection.update_one(
            {"user_id": user_id},
            {"$set": user_data},
            upsert=True
        )
        logger.info("Saved user %d to database.", user_id)

    async def delete_user(self, user_id: int):
        """Delete a user document."""
        db = self._get_db(user_id)
        if not db:
            return
        collection = db["users"]
        await collection.delete_one({"user_id": user_id})
        logger.info("Deleted user %d.", user_id)

    # Similarly, methods for groups, channels, premium, etc.
