"""
Not-found request tracking.
Stores per-user requests when a search returns no result.
TTL-expiring records. Prevent duplicate requests per (user, query).
"""
import logging
import time
from typing import Optional

from database import db_registry

logger = logging.getLogger(__name__)

REQUEST_TTL = 7 * 24 * 3600   # 7 days


class RequestRepository:
    def _coll(self):
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db["search_requests"]

    async def ensure_indexes(self) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.create_index("expires_at", expireAfterSeconds=0)
            await c.create_index([("user_id", 1), ("normalized_query", 1), ("status", 1)])
        except Exception as e:
            logger.warning(f"[REQUESTS] index failed: {e}")

    async def add(self, user_id: int, normalized_query: str,
                  raw_query: str, mode: str = "movie") -> bool:
        """
        Add a not-found request. Skips if an active one already exists.
        Returns True if created.
        """
        c = self._coll()
        if c is None:
            return False
        try:
            existing = await c.find_one({
                "user_id": user_id,
                "normalized_query": normalized_query,
                "status": {"$in": ["not_found", "not_released", "unavailable"]},
            })
            if existing:
                return False
            now = time.time()
            await c.insert_one({
                "user_id": user_id,
                "raw_query": raw_query,
                "normalized_query": normalized_query,
                "mode": mode,
                "status": "not_found",
                "created_at": now,
                "expires_at": now + REQUEST_TTL,
            })
            logger.info(f"[REQUESTS] new request: user={user_id} query='{raw_query}'")
            return True
        except Exception as e:
            logger.warning(f"[REQUESTS] add failed: {e}")
            return False

    async def mark_fulfilled(self, normalized_query: str) -> int:
        c = self._coll()
        if c is None:
            return 0
        try:
            r = await c.update_many(
                {"normalized_query": normalized_query,
                 "status": {"$in": ["not_found", "not_released", "unavailable"]}},
                {"$set": {"status": "fulfilled", "fulfilled_at": time.time()}},
            )
            return r.modified_count
        except Exception:
            return 0

    async def count_recent(self, hours: int = 24) -> int:
        c = self._coll()
        if c is None:
            return 0
        try:
            since = time.time() - hours * 3600
            return await c.count_documents({"created_at": {"$gte": since}})
        except Exception:
            return 0
    # ═══════════════════════ REQUEST TOKENS ═══════════════════════
    async def create_token(self, user_id: int, username: str, full_name: str,
                           movie_name: str, imdb_id: Optional[str] = None,
                           user_query: str = "") -> Optional[str]:
        """Create a request token. Returns token_id."""
        c = self._coll()
        if c is None:
            return None
        import uuid
        import time as _t
        token_id = uuid.uuid4().hex[:12]
        now = _t.time()
        try:
            await c.insert_one({
                "token_id": token_id,
                "user_id": user_id,
                "username": username or "",
                "full_name": full_name or "",
                "movie_name": movie_name,
                "imdb_id": imdb_id,
                "user_query": user_query or movie_name,
                "status": "pending",
                "created_at": now,
                "expires_at": now + (7 * 24 * 3600),
            })
            return token_id
        except Exception as e:
            logger.warning(f"[REQUESTS] create_token failed: {e}")
            return None

    async def get_token(self, token_id: str) -> Optional[Dict]:
        c = self._coll()
        if c is None:
            return None
        try:
            return await c.find_one({"token_id": token_id})
        except Exception:
            return None

    async def update_token(self, token_id: str, status: str) -> bool:
        c = self._coll()
        if c is None:
            return False
        try:
            r = await c.update_one(
                {"token_id": token_id},
                {"$set": {"status": status, "updated_at": __import__("time").time()}},
            )
            return r.matched_count > 0
        except Exception as e:
            logger.warning(f"[REQUESTS] update_token failed: {e}")
            return False

    async def delete_token(self, token_id: str) -> bool:
        c = self._coll()
        if c is None:
            return False
        try:
            r = await c.delete_one({"token_id": token_id})
            logger.info(f"[REQUESTS] token {token_id} cleared from cache")
            return r.deleted_count > 0
        except Exception as e:
            logger.warning(f"[REQUESTS] delete_token failed: {e}")
            return False

requests = RequestRepository()
