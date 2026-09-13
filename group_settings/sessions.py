"""
Multi-step UI session state.
Stored in MongoDB with TTL index — auto-cleans expired sessions.
"""
import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from database import db_registry

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes


class GroupSessionManager:
    def _coll(self):
        db = db_registry.get_system_db()
        return db["group_sessions"] if db is not None else None

    async def ensure_indexes(self) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.create_index("expires_at", expireAfterSeconds=0)
            await c.create_index("user_id")
            await c.create_index("chat_id")
            await c.create_index("token", unique=True)
        except Exception as e:
            logger.warning(f"[SESS] index creation failed: {e}")

    async def start(self, user_id: int, chat_id: int, action: str,
                    payload: Optional[Dict[str, Any]] = None,
                    ttl: int = DEFAULT_TTL_SECONDS,
                    prompt_msg_id: Optional[int] = None) -> str:
        c = self._coll()
        if c is None:
            return ""
        token = secrets.token_urlsafe(9)[:12]
        now = time.time()
        doc = {
            "token": token,
            "user_id": user_id,
            "chat_id": chat_id,
            "action": action,
            "step": 1,
            "payload": payload or {},
            "prompt_msg_id": prompt_msg_id,     # ← NEW: which message to reply to
            "created_at": now,
            "expires_at": now + ttl,
        }
        try:
            await c.insert_one(doc)
            return token
        except Exception as e:
            logger.warning(f"[SESS] start failed: {e}")
            return ""

    async def get(self, token: str) -> Optional[Dict[str, Any]]:
        c = self._coll()
        if c is None:
            return None
        try:
            doc = await c.find_one({"token": token})
            if not doc:
                return None
            if doc.get("expires_at", 0) < time.time():
                await c.delete_one({"token": token})
                return None
            doc.pop("_id", None)
            return doc
        except Exception:
            return None

    async def advance(self, token: str, patch: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        c = self._coll()
        if c is None:
            return None
        patch = patch or {}
        try:
            r = await c.find_one_and_update(
                {"token": token},
                {
                    "$inc": {"step": 1},
                    "$set": {
                        **{f"payload.{k}": v for k, v in patch.items()},
                        "expires_at": time.time() + DEFAULT_TTL_SECONDS,
                    },
                },
                return_document=True,
            )
            if r:
                r.pop("_id", None)
            return r
        except Exception as e:
            logger.warning(f"[SESS] advance failed: {e}")
            return None

    async def cancel(self, token: str) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.delete_one({"token": token})
        except Exception:
            pass

    async def cleanup(self) -> int:
        c = self._coll()
        if c is None:
            return 0
        try:
            r = await c.delete_many({"expires_at": {"$lt": time.time()}})
            return r.deleted_count
        except Exception:
            return 0


session_manager = GroupSessionManager()
