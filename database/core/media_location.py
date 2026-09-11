from typing import Optional, Dict, Any
from database import db_registry

class MediaLocationRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_core_db()
            self._collection = db["media_location_registry"]
        return self._collection

    async def get_location(self, file_id: str) -> Optional[int]:
        doc = await self._get_collection().find_one({"file_id": file_id})
        return doc.get("shard_index") if doc else None

    async def set_location(self, file_id: str, shard_index: int) -> None:
        await self._get_collection().update_one(
            {"file_id": file_id},
            {"$set": {"shard_index": shard_index}},
            upsert=True
        )
