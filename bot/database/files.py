"""
File / Media database service.

Supports multiple file databases (FILE_DATABASE_URI_1, _2, ...).
Provides methods to store/search movie records, file links, etc.
"""

import logging
from typing import Any, Dict, Optional, List

from bot.database.manager import DatabaseManager
from bot.database.registry import DatabaseRegistry

logger = logging.getLogger("database.files")

class FileDatabase:
    """
    High-level API for file/movie indexing databases.
    """

    def __init__(self, manager: DatabaseManager, registry: DatabaseRegistry):
        self.manager = manager
        self.registry = registry
        self._dbs: Dict[str, Any] = {}

    async def initialize(self):
        """Fetch all file database objects."""
        for info in self.registry.get_all():
            if info.type == "file":
                db = self.manager.get_registered_database(info.key)
                if db:
                    self._dbs[info.key] = db
                    logger.info("Initialized file database '%s'.", info.friendly_name)
                else:
                    logger.error("Could not initialize file database '%s'.", info.friendly_name)

    def _get_db(self, file_id: str = None) -> Optional[Any]:
        """Pick a database. If file_id is provided, hash it for consistency."""
        if not self._dbs:
            logger.warning("No file databases available.")
            return None
        if file_id is None:
            key = next(iter(self._dbs))
        else:
            keys = sorted(self._dbs.keys())
            index = hash(file_id) % len(keys)
            key = keys[index]
        return self._dbs[key]

    async def add_file(self, file_record: Dict):
        """Insert or update a file/movie record."""
        file_id = file_record.get("file_id")
        if not file_id:
            logger.error("Cannot add file without file_id.")
            return
        db = self._get_db(file_id)
        if not db:
            logger.error("No file database available to add file.")
            return
        collection = db["files"]
        await collection.update_one(
            {"file_id": file_id},
            {"$set": file_record},
            upsert=True
        )
        logger.info("Added/updated file %s to database.", file_id)

    async def search_files(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Simple search using regex on 'title' or 'file_name'.
        In production, you'd use text indexes for speed.
        """
        results = []
        for db in self._dbs.values():
            collection = db["files"]
            cursor = collection.find({"$or": [
                {"title": {"$regex": query, "$options": "i"}},
                {"file_name": {"$regex": query, "$options": "i"}}
            ]}).limit(limit)
            async for doc in cursor:
                results.append(doc)
            if len(results) >= limit:
                break
        logger.debug("Search query '%s' returned %d results.", query, len(results))
        return results[:limit]

    async def remove_file(self, file_id: str):
        """Delete a file record."""
        db = self._get_db(file_id)
        if not db:
            return
        collection = db["files"]
        await collection.delete_one({"file_id": file_id})
        logger.info("Deleted file %s.", file_id)
