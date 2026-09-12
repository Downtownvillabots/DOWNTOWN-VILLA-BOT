from typing import Optional, Dict, Any
from database import db_registry
from database.core.media_location import MediaLocationRepository

class MediaFileRepository:
    def __init__(self):
        self._location_repo = MediaLocationRepository()

    def _get_collection(self, shard_index: int):
        db = db_registry.get_media_db(shard_index)
        return db["media_files"]

    async def add_file(self, file_id: str, data: Dict[str, Any]) -> int:
        shard_count = db_registry.get_media_shard_count()
        if shard_count == 0:
            raise RuntimeError("No media database shards configured.")
        db = db_registry.get_media_db()  # advances index
        # Get the index that was used (registry internal)
        shard_index = db_registry._media_shard_index  # okay for now
        collection = self._get_collection(shard_index)
        await collection.update_one(
            {"file_id": file_id},
            {"$set": data},
            upsert=True
        )
        await self._location_repo.set_location(file_id, shard_index)
        return shard_index

    async def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        shard_index = await self._location_repo.get_location(file_id)
        if shard_index is None:
            return None
        collection = self._get_collection(shard_index)
        return await collection.find_one({"file_id": file_id})
