from typing import List
from database.connection import DatabaseManager

class DatabaseRegistry:
    def __init__(self, manager: DatabaseManager):
        self._manager = manager

    def system_entries(self) -> List:
        return self._manager.get_system_entries()

    def user_entries(self) -> List:
        return self._manager.get_user_entries()

    def media_entries(self) -> List:
        return self._manager.get_media_entries()

    def system_dbs(self) -> List:
        return [e.db for e in self._manager.get_system_entries()]

    def user_dbs(self) -> List:
        return [e.db for e in self._manager.get_user_entries()]

    def media_dbs(self) -> List:
        return [e.db for e in self._manager.get_media_entries()]

    # Legacy accessors kept for other modules
    def get_system_db(self):
        return self._manager.get_system_db()

    def get_user_db(self):
        return self._manager.get_user_db()

    def get_catalog_db(self):
        return self._manager.get_catalog_db()

    def get_media_db(self, i: int = 0):
        return self._manager.get_media_db(i)

    def get_media_shard_count(self) -> int:
        return self._manager.get_media_db_count()
