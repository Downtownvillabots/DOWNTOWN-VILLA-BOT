from typing import Optional, Dict, Any
from database import db_registry

class EpisodeRepository:
    def __init__(self):
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            db = db_registry.get_catalog_db()
            self._collection = db["episodes"]
        return self._collection

    async def get_episode(self, series_id: int, season: int, episode: int) -> Optional[Dict[str, Any]]:
        return await self._get_collection().find_one({
            "series_id": series_id,
            "season": season,
            "episode": episode
        })

    async def upsert_episode(self, series_id: int, season: int, episode: int, data: Dict[str, Any]) -> None:
        await self._get_collection().update_one(
            {"series_id": series_id, "season": season, "episode": episode},
            {"$set": data},
            upsert=True
        )
