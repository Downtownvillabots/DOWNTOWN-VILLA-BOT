from typing import Optional, Dict, Any
from database import db_registry

class IndexingRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_core_db()
            self._collection = db["indexing_requests"]
        return self._collection

    async def create_request(self, data: Dict[str, Any]) -> None:
        await self._get_collection().insert_one(data)

    async def get_pending_requests(self, limit: int = 10):
        cursor = self._get_collection().find({"status": "pending"}).limit(limit)
        return await cursor.to_list(length=limit)
