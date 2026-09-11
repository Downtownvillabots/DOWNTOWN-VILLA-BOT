from typing import Optional, Dict, Any
from database import db_registry

class BotStateRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_core_db()
            self._collection = db["bot_state"]
        return self._collection

    async def get_state(self, key: str) -> Optional[Any]:
        doc = await self._get_collection().find_one({"key": key})
        return doc.get("value") if doc else None

    async def set_state(self, key: str, value: Any) -> None:
        await self._get_collection().update_one(
            {"key": key},
            {"$set": {"value": value}},
            upsert=True
        )
