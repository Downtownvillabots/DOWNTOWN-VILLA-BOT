"""
Dynamic media shard discovery.
Never hardcodes a shard count.
"""
import logging
from typing import List

from database import db_registry

logger = logging.getLogger(__name__)


class MediaRegistry:
    """Thin wrapper over db_registry to list all media shards."""

    @staticmethod
    def all_shards() -> List:
        """Return list of media pool entries: [{index, label, db}]"""
        return db_registry.media_entries()

    @staticmethod
    def all_dbs() -> List:
        return [e.db for e in db_registry.media_entries()]

    @staticmethod
    def shard_count() -> int:
        return len(db_registry.media_entries())

    @staticmethod
    def get_shard(index: int):
        for e in db_registry.media_entries():
            if e.index == index:
                return e.db
        return None


media_registry = MediaRegistry()
