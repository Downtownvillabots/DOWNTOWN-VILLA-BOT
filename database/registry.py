import logging
from typing import Optional
from database.connection import DatabaseManager

logger = logging.getLogger(__name__)

class DatabaseRegistry:
    def __init__(self, manager: DatabaseManager):
        self._manager = manager
        self._media_shard_index = 0

    def get_system_db(self):
        return self._manager.get_system_db()

    def get_user_db(self):
        return self._manager.get_user_db()

    def get_catalog_db(self):
        return self._manager.get_catalog_db()

    def get_media_db(self, shard_index: Optional[int] = None):
        if shard_index is not None:
            return self._manager.get_media_db(shard_index)
        count = self._manager.get_media_db_count()
        if count == 0:
            return self._manager.get_user_db()
        db = self._manager.get_media_db(self._media_shard_index)
        self._media_shard_index = (self._media_shard_index + 1) % count
        return db

    def get_media_shard_count(self) -> int:
        return self._manager.get_media_db_count()
