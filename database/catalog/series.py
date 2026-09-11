from typing import Optional, Dict, Any
from database import db_registry

class SeriesRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_catalog_db()
            self._collection = db["series_catalog"]
        return self._collection

    async def get_series(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        return await self._get_collection().find_one({"tmdb_id": tmdb_id})

    async def upsert_series(self, tmdb_id: int, data: Dict[str, Any]) -> None:
        await self._get_collection().update_one(
            {"tmdb_id": tmdb_id},
            {"$set": data},
            upsert=True
        )
