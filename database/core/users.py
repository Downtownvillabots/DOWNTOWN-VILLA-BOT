from typing import Optional, Dict, Any
from database import db_registry

class UserRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_user_db()
            self._collection = db["users"]
        return self._collection

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        return await self._get_collection().find_one({"user_id": user_id})

    async def create_or_update_user(self, user_id: int, data: Dict[str, Any]) -> None:
        await self._get_collection().update_one(
            {"user_id": user_id},
            {"$set": data},
            upsert=True
        )

    async def is_premium(self, user_id: int) -> bool:
        user = await self.get_user(user_id)
        return user.get("is_premium", False) if user else False

    async def set_premium(self, user_id: int, status: bool, expiry: Optional[int] = None) -> None:
        data = {"is_premium": status}
        if expiry is not None:
            data["premium_expiry"] = expiry
        await self.create_or_update_user(user_id, data)

    async def get_user_count(self) -> int:
        return await self._get_collection().estimated_document_count()
