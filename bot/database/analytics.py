"""
Database statistics & analytics.

Gathers real statistics from each database (documents, sizes, indexes).
Computes totals across system/user/file groups.
"""

import logging
from typing import Dict, List, Any

from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry

logger = logging.getLogger("database.analytics")

class DatabaseAnalytics:
    """Provides methods to get detailed stats and totals."""

    def __init__(self, manager: DatabaseManager, registry: DatabaseRegistry):
        self.manager = manager
        self.registry = registry

    async def get_database_stats(self, key: str) -> Dict[str, Any]:
        """
        Get detailed stats for a single database.
        Returns a dictionary of metrics (or empty if error).
        """
        info = self.registry.get_info(key)
        if not info:
            logger.error("Analytics: unknown key '%s'.", key)
            return {}
        db = self.manager.get_registered_database(key)
        if db is None:
            return {"status": "🔴 OFFLINE"}
        try:
            stats = await db.command("dbStats")
            return {
                "status": "🟢 ONLINE",
                "collections": stats.get("collections", 0),
                "documents": stats.get("objects", 0),
                "data_size": stats.get("dataSize", 0),
                "storage_size": stats.get("storageSize", 0),
                "index_size": stats.get("indexSize", 0),
                "total_size": stats.get("dataSize", 0) + stats.get("indexSize", 0),
                "avg_object_size": stats.get("avgObjSize", 0),
            }
        except Exception as e:
            logger.error("Failed to get stats for '%s': %s", key, e)
            return {"status": "🔴 OFFLINE", "error": str(e)}

    async def get_total_stats(self, db_type: str = None) -> Dict[str, Any]:
        """
        Aggregate totals for all databases, optionally filtered by type ('system', 'user', 'file').
        """
        totals = {
            "databases": 0,
            "collections": 0,
            "documents": 0,
            "data_size": 0,
            "storage_size": 0,
            "index_size": 0,
            "total_size": 0,
        }
        for info in self.registry.get_all():
            if db_type and info.type != db_type:
                continue
            stats = await self.get_database_stats(info.key)
            if stats.get("status") != "🟢 ONLINE":
                continue
            totals["databases"] += 1
            totals["collections"] += stats.get("collections", 0)
            totals["documents"] += stats.get("documents", 0)
            totals["data_size"] += stats.get("data_size", 0)
            totals["storage_size"] += stats.get("storage_size", 0)
            totals["index_size"] += stats.get("index_size", 0)
            totals["total_size"] += stats.get("total_size", 0)
        logger.debug("Calculated totals for type '%s': %s", db_type, totals)
        return totals
