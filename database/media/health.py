from typing import Dict, Any
from database import db_registry

class MediaHealthRepository:
    async def get_shard_stats(self) -> Dict[str, Any]:
        stats = {}
        for i in range(db_registry.get_media_shard_count()):
            db = db_registry.get_media_db(i)
            count = await db["media_files"].estimated_document_count()
            stats[f"shard_{i}"] = {"count": count}
        return stats
