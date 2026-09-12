from typing import Optional, Any
from database import db_registry

class MonitoringStateRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_system_db()
            self._collection = db["monitoring_state"]
        return self._collection

    async def get_metric(self, name: str) -> Optional[Any]:
        doc = await self._get_collection().find_one({"name": name})
        return doc.get("value") if doc else None

    async def set_metric(self, name: str, value: Any) -> None:
        await self._get_collection().update_one(
            {"name": name},
            {"$set": {"value": value}},
            upsert=True
        )
