"""
Indexing job state persistence for manual backward indexing.
Allows pause/resume/restart-safe behaviour.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import db_registry

logger = logging.getLogger(__name__)


class IndexingJobRepository:
    def _coll(self):
        db = db_registry.get_system_db()
        return db["indexing_jobs"] if db is not None else None

    async def create(self, job: Dict[str, Any]) -> Optional[str]:
        c = self._coll()
        if c is None:
            return None
        job = dict(job)
        job.setdefault("created_at", datetime.utcnow())
        job["updated_at"] = datetime.utcnow()
        try:
            r = await c.insert_one(job)
            return str(r.inserted_id)
        except Exception as e:
            logger.warning(f"Job create failed: {e}")
            return None

    async def update(self, job_id: str, patch: Dict[str, Any]) -> None:
        c = self._coll()
        if c is None:
            return
        from bson import ObjectId
        try:
            patch = dict(patch)
            patch["updated_at"] = datetime.utcnow()
            await c.update_one({"_id": ObjectId(job_id)}, {"$set": patch})
        except Exception as e:
            logger.warning(f"Job update failed: {e}")

    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        c = self._coll()
        if c is None:
            return None
        from bson import ObjectId
        try:
            return await c.find_one({"_id": ObjectId(job_id)})
        except Exception:
            return None

    async def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        c = self._coll()
        if c is None:
            return []
        try:
            cur = c.find({}).sort("created_at", -1).limit(limit)
            return await cur.to_list(length=limit)
        except Exception:
            return []


indexing_jobs = IndexingJobRepository()
