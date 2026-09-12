from typing import Optional, Dict, Any
from database import db_registry

class GroupRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_user_db()
            self._collection = db["groups"]
        return self._collection

    async def get_group(self, group_id: int) -> Optional[Dict[str, Any]]:
        return await self._get_collection().find_one({"group_id": group_id})

    async def create_or_update_group(self, group_id: int, data: Dict[str, Any]) -> None:
        await self._get_collection().update_one(
            {"group_id": group_id},
            {"$set": data},
            upsert=True
        )

    async def get_group_count(self) -> int:
        return await self._get_collection().estimated_document_count()
