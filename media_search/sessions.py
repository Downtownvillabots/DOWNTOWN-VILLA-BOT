"""
Search session persistence.
Stores per-user selection state with TTL expiry.
Uses system database (database.db_registry.get_system_db()).
"""
import logging
import time
import uuid
from datetime import datetime
from typing import Optional

from database import db_registry
from media_search.config import SESSION_TTL
from media_search.models import SearchSession

logger = logging.getLogger(__name__)


class SessionRepository:
    def _coll(self):
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db["search_sessions"]

    async def ensure_indexes(self) -> None:
        """TTL index on expires_at. Safe to call multiple times."""
        c = self._coll()
        if c is None:
            return
        try:
            await c.create_index("session_id", unique=True)
            await c.create_index("expires_at", expireAfterSeconds=0)
            await c.create_index([("user_id", 1), ("chat_id", 1)])
        except Exception as e:
            logger.warning(f"[SESSIONS] index creation failed: {e}")

    async def create(self, user_id: int, chat_id: int, query: str,
                     normalized_query: str, mode: str = "movie",
                     candidates: Optional[list] = None) -> Optional[SearchSession]:
        c = self._coll()
        if c is None:
            return None
        now = time.time()
        session = SearchSession(
            session_id=uuid.uuid4().hex[:12],
            user_id=user_id,
            chat_id=chat_id,
            query=query,
            normalized_query=normalized_query,
            mode=mode,
            candidates=candidates or [],
            created_at=now,
            updated_at=now,
            expires_at=now + SESSION_TTL,
        )
        try:
            await c.insert_one(session.to_mongo())
            return session
        except Exception as e:
            logger.warning(f"[SESSIONS] create failed: {e}")
            return None

    async def get(self, session_id: str) -> Optional[SearchSession]:
        c = self._coll()
        if c is None:
            return None
        try:
            doc = await c.find_one({"session_id": session_id})
            if not doc:
                return None
            if doc.get("expires_at", 0) < time.time():
                return None
            return SearchSession.from_mongo(doc)
        except Exception as e:
            logger.warning(f"[SESSIONS] get failed: {e}")
            return None

    async def update(self, session_id: str, **patch) -> bool:
        c = self._coll()
        if c is None:
            return False
        patch["updated_at"] = time.time()
        patch["expires_at"] = time.time() + SESSION_TTL
        try:
            r = await c.update_one({"session_id": session_id}, {"$set": patch})
            return r.modified_count > 0 or r.matched_count > 0
        except Exception as e:
            logger.warning(f"[SESSIONS] update failed: {e}")
            return False

    async def delete(self, session_id: str) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.delete_one({"session_id": session_id})
        except Exception:
            pass

    async def cleanup_expired(self) -> int:
        """Manual cleanup (TTL index handles this automatically)."""
        c = self._coll()
        if c is None:
            return 0
        try:
            r = await c.delete_many({"expires_at": {"$lt": time.time()}})
            return r.deleted_count
        except Exception:
            return 0


sessions = SessionRepository()
