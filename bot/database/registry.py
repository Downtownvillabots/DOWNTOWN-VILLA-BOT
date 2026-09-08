# bot/database/registry.py
"""
Database registry.

Discovers all configured databases from environment variables,
assigns friendly IDs (e.g., SYSTEM-DB, USER-DB-01, FILE-DB-02),
and tracks their status.
"""

import asyncio  # <-- ADDED THIS LINE
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bot.config import Config
from bot.database.manager import DatabaseManager

logger = logging.getLogger("database.registry")

@dataclass
class DatabaseInfo:
    """Stores metadata about a database instance."""
    key: str               # internal unique key (e.g., "system", "user_1")
    friendly_name: str     # display name (e.g., "SYSTEM-DB", "USER-DB-01")
    uri: str               # full connection string (never shown in UI)
    db_name: Optional[str] = None
    type: str = ""         # "system", "user", "file"
    status: str = "🟢 ONLINE"
    collections_count: int = 0
    documents_count: int = 0
    data_size_bytes: int = 0
    storage_size_bytes: int = 0
    index_size_bytes: int = 0
    total_size_bytes: int = 0

class DatabaseRegistry:
    """
    Discovers and registers all databases.
    Provides methods to list, get info, and update statistics.
    """

    def __init__(self, manager: DatabaseManager):
        self.manager = manager
        self._infos: Dict[str, DatabaseInfo] = {}

    async def discover(self):
        """Scan Config for URIs and create DatabaseInfo objects."""
        # System database
        if Config.SYSTEM_DATABASE_URI:
            self._infos["system"] = DatabaseInfo(
                key="system",
                friendly_name="SYSTEM-DB",
                uri=Config.SYSTEM_DATABASE_URI,
                type="system"
            )
            logger.info("Discovered system database.")
        else:
            logger.debug("No system database configured.")

        # User databases
        for idx, uri in enumerate(Config.USER_DATABASE_URIS, start=1):
            key = f"user_{idx}"
            self._infos[key] = DatabaseInfo(
                key=key,
                friendly_name=f"USER-DB-{idx:02d}",
                uri=uri,
                type="user"
            )
            logger.info("Discovered user database %d.", idx)

        # File databases
        for idx, uri in enumerate(Config.FILE_DATABASE_URIS, start=1):
            key = f"file_{idx}"
            self._infos[key] = DatabaseInfo(
                key=key,
                friendly_name=f"FILE-DB-{idx:02d}",
                uri=uri,
                type="file"
            )
            logger.info("Discovered file database %d.", idx)

        # Register each in the manager
        for info in self._infos.values():
            await self.manager.register_database(info.key, info.uri)

        # If no databases configured, log a warning
        if not self._infos:
            logger.warning("No database URIs configured. Bot will run without persistent storage.")

    def get_all(self) -> List[DatabaseInfo]:
        """Return a list of all DatabaseInfo objects."""
        return list(self._infos.values())

    def get_info(self, key: str) -> Optional[DatabaseInfo]:
        """Return DatabaseInfo for a given key."""
        return self._infos.get(key)

    async def update_stats(self, key: str):
        """
        Update the statistics for a database by querying MongoDB.
        This should be called periodically or on demand.
        """
        info = self._infos.get(key)
        if not info:
            logger.error("Cannot update stats for unknown key '%s'", key)
            return

        db = self.manager.get_registered_database(key)
        if db is None:
            info.status = "🔴 OFFLINE"
            logger.warning("Database '%s' not registered in manager.", key)
            return

        try:
            # Get database statistics
            stats = await db.command("dbStats")
            info.collections_count = stats.get("collections", 0)
            info.documents_count = stats.get("objects", 0)
            info.data_size_bytes = stats.get("dataSize", 0)
            info.storage_size_bytes = stats.get("storageSize", 0)
            info.index_size_bytes = stats.get("indexSize", 0)
            info.total_size_bytes = stats.get("dataSize", 0) + stats.get("indexSize", 0)
            info.status = "🟢 ONLINE"
            logger.debug("Updated stats for '%s': docs=%d, data=%d", key, info.documents_count, info.data_size_bytes)
        except Exception as e:
            info.status = "🔴 OFFLINE"
            logger.error("Failed to get stats for '%s': %s", key, e)

    async def update_all_stats(self):
        """Update statistics for all databases in parallel."""
        tasks = [self.update_stats(key) for key in self._infos.keys()]
        await asyncio.gather(*tasks)

    def get_status_summary(self) -> Dict[str, str]:
        """Return a dict of key -> status for quick display."""
        return {key: info.status for key, info in self._infos.items()}
