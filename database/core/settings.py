from typing import Optional, Dict, Any
from database import db_registry

class SettingsRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_core_db()
            self._collection = db["settings"]
        return self._collection

    async def get_setting(self, key: str) -> Optional[Any]:
        doc = await self._get_collection().find_one({"key": key})
        return doc.get("value") if doc else None

    async def set_setting(self, key: str, value: Any) -> None:
        await self._get_collection().update_one(
            {"key": key},
            {"$set": {"value": value}},
            upsert=True
        )
