"""
Group Config Manager — CRUD on the `groups` collection.

Uses atomic $set updates. All reads pass through TTL cache.
The `chat_id` field is the unique key.
"""
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import db_registry
from group_settings.cache import config_cache

logger = logging.getLogger(__name__)


# ═══════════════════════ DEFAULTS ═══════════════════════
DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "content_mode": "both",                         # "movies" | "series" | "both"
    "movie_group_link": None,
    "series_group_link": None,
    "result_mode": "button",                        # "button" | "text"
    "result_buttons": [],
    "custom_caption": None,                         # None → global
    "search_settings": {
        "auto_filter": True,
        "spell_check": True,
        "query_cleaning": True,
        "quality_filter": True,
        "language_filter": True,
        "season_filter": True,
        "results_per_page": 10,
        "search_cooldown": 2,
    },
    "metadata_settings": {
        "poster": True,
        "rating": True,
        "genre": True,
        "year": True,
        "language": True,
    },
    "force_sub_settings": {
        "enabled": False,
        "channels": [],
    },
    "verification_settings": {
        "enabled": False,
        "shortener_1": None,
        "shortener_2": None,
        "shortener_3": None,
        "tutorial_1": None,
        "tutorial_2": None,
        "tutorial_3": None,
        "verify_time": 1200,
        "third_verify_time": 54000,
    },
    "security_settings": {
        "url_blocking": True,
        "telegram_links": True,
        "admin_bypass": True,
        "search_flood_control": True,
        "request_flood_control": True,
        "search_limit": 5,
        "request_limit": 3,
    },
    "welcome_settings": {
        "enabled": False,
        "photo_url": None,
        "message": None,
        "button_text": None,
        "button_url": None,
        "auto_delete": True,
        "delete_after_seconds": 600,
    },
    "auto_delete_settings": {
        "welcome": True,
        "result": True,
        "search": True,
        "file": True,
        "delete_after_seconds": 600,
    },
    "request_settings": {
        "enabled": True,
        "no_result_log": True,
        "request_channel": None,
        "user_pm_update": True,
        "duplicate_check": True,
    },
}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Recursively merge override into base (returns new dict)."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _flatten_patch(prefix: str, value: Any) -> Dict[str, Any]:
    """Convert nested dict to dotted-path keys for atomic $set."""
    out: Dict[str, Any] = {}
    if isinstance(value, dict):
        for k, v in value.items():
            out.update(_flatten_patch(f"{prefix}.{k}", v))
    else:
        out[prefix] = value
    return out


# ═══════════════════════ MANAGER ═══════════════════════
class GroupConfigManager:
    def _coll(self):
        db = db_registry.get_user_db()
        return db["groups"] if db is not None else None

    async def ensure_indexes(self) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.create_index("chat_id", unique=True)
            await c.create_index("enabled")
            await c.create_index("content_mode")
            await c.create_index("title")
            await c.create_index("username")
        except Exception as e:
            logger.warning(f"[GROUP] index creation failed: {e}")

    # ────────── READ ──────────
    async def get_config(self, chat_id: int, use_cache: bool = True) -> Dict[str, Any]:
        """Return full config with defaults merged. Cached."""
        if use_cache:
            cached = config_cache.get(chat_id)
            if cached is not None:
                return cached

        c = self._coll()
        if c is None:
            return {"chat_id": chat_id, **DEFAULT_CONFIG}

        try:
            doc = await c.find_one({"chat_id": chat_id})
        except Exception as e:
            logger.warning(f"[GROUP] get_config failed for {chat_id}: {e}")
            doc = None

        if not doc:
            # Not registered yet — return defaults
            merged = {"chat_id": chat_id, **DEFAULT_CONFIG}
            if use_cache:
                config_cache.set(chat_id, merged)
            return merged

        # Strip _id, merge defaults
        doc.pop("_id", None)
        merged = _deep_merge(DEFAULT_CONFIG, doc)
        merged["chat_id"] = chat_id
        merged["title"] = doc.get("title")
        merged["username"] = doc.get("username")
        merged["created_at"] = doc.get("created_at")
        merged["updated_at"] = doc.get("updated_at")

        if use_cache:
            config_cache.set(chat_id, merged)
        return merged

    async def get_config_fresh(self, chat_id: int) -> Dict[str, Any]:
        return await self.get_config(chat_id, use_cache=False)

    async def get_raw(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Return the raw DB doc (no defaults merged)."""
        c = self._coll()
        if c is None:
            return None
        try:
            doc = await c.find_one({"chat_id": chat_id})
            if doc:
                doc.pop("_id", None)
            return doc
        except Exception:
            return None

    # ────────── WRITE ──────────
    async def register_group(self, chat_id: int, title: str,
                             username: Optional[str] = None) -> bool:
        """Create group config if missing. Idempotent."""
        c = self._coll()
        if c is None:
            return False
        now = datetime.utcnow()
        try:
            await c.update_one(
                {"chat_id": chat_id},
                {
                    "$setOnInsert": {
                        "chat_id": chat_id,
                        "created_at": now,
                        **DEFAULT_CONFIG,
                    },
                    "$set": {
                        "title": title,
                        "username": username,
                        "updated_at": now,
                    },
                },
                upsert=True,
            )
            config_cache.invalidate(chat_id)
            logger.info(f"[GROUP] registered {chat_id} ({title!r})")
            return True
        except Exception as e:
            logger.warning(f"[GROUP] register failed {chat_id}: {e}")
            return False

    async def update_config(self, chat_id: int, patch: Dict[str, Any]) -> bool:
        """Atomic nested patch. Invalidates cache."""
        c = self._coll()
        if c is None:
            return False
        # Flatten for atomic $set
        flat: Dict[str, Any] = {}
        for k, v in patch.items():
            flat.update(_flatten_patch(k, v))
        flat["updated_at"] = datetime.utcnow()

        try:
            await c.update_one(
                {"chat_id": chat_id},
                {"$set": flat},
                upsert=True,
            )
            config_cache.invalidate(chat_id)
            return True
        except Exception as e:
            logger.warning(f"[GROUP] update failed {chat_id}: {e}")
            return False

    async def set_field(self, chat_id: int, field_path: str, value: Any) -> bool:
        """Set a single dotted-path field."""
        return await self.update_config(chat_id, {field_path: value})

    async def reset_config(self, chat_id: int) -> bool:
        """Wipe group config, restore defaults. Keeps chat_id + title."""
        c = self._coll()
        if c is None:
            return False
        doc = await self.get_raw(chat_id) or {}
        title = doc.get("title")
        username = doc.get("username")
        now = datetime.utcnow()
        try:
            await c.replace_one(
                {"chat_id": chat_id},
                {
                    "chat_id": chat_id,
                    "title": title,
                    "username": username,
                    "created_at": doc.get("created_at", now),
                    "updated_at": now,
                    **DEFAULT_CONFIG,
                },
                upsert=True,
            )
            config_cache.invalidate(chat_id)
            return True
        except Exception as e:
            logger.warning(f"[GROUP] reset failed {chat_id}: {e}")
            return False

    async def delete_group(self, chat_id: int) -> bool:
        c = self._coll()
        if c is None:
            return False
        try:
            await c.delete_one({"chat_id": chat_id})
            config_cache.invalidate(chat_id)
            return True
        except Exception:
            return False

    async def toggle_enabled(self, chat_id: int) -> bool:
        current = await self.get_config(chat_id)
        new_val = not current.get("enabled", True)
        await self.set_field(chat_id, "enabled", new_val)
        return new_val

    # ────────── LIST / SEARCH (owner UI) ──────────
    async def list_groups(self, offset: int = 0, limit: int = 20) -> List[Dict[str, Any]]:
        c = self._coll()
        if c is None:
            return []
        try:
            cur = c.find({}).sort("title", 1).skip(offset).limit(limit)
            return await cur.to_list(length=limit)
        except Exception as e:
            logger.warning(f"[GROUP] list_groups failed: {e}")
            return []

    async def count_groups(self) -> int:
        c = self._coll()
        if c is None:
            return 0
        try:
            return await c.estimated_document_count()
        except Exception:
            return 0

    async def search_groups(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search by title (regex), username, or chat_id (exact)."""
        c = self._coll()
        if c is None:
            return []
        q = (query or "").strip()
        if not q:
            return []

        import re
        safe = re.escape(q)
        or_clauses: List[Dict[str, Any]] = [
            {"title": {"$regex": safe, "$options": "i"}},
            {"username": {"$regex": safe, "$options": "i"}},
        ]
        # Numeric chat_id search
        try:
            cid = int(q)
            or_clauses.append({"chat_id": cid})
        except ValueError:
            pass

        try:
            cur = c.find({"$or": or_clauses}).limit(limit)
            return await cur.to_list(length=limit)
        except Exception as e:
            logger.warning(f"[GROUP] search_groups failed: {e}")
            return []

    # ────────── USER ↔ GROUP CONNECTIONS ──────────
    def _conn_coll(self):
        db = db_registry.get_user_db()
        return db["user_group_connections"] if db is not None else None

    async def connect_user_group(self, user_id: int, chat_id: int) -> bool:
        c = self._conn_coll()
        if c is None:
            return False
        try:
            await c.update_one(
                {"_id": user_id},
                {
                    "$addToSet": {"group_ids": chat_id},
                    "$set": {"updated_at": datetime.utcnow()},
                },
                upsert=True,
            )
            return True
        except Exception as e:
            logger.warning(f"[GROUP] connect failed: {e}")
            return False

    async def disconnect_user_group(self, user_id: int, chat_id: int) -> bool:
        c = self._conn_coll()
        if c is None:
            return False
        try:
            await c.update_one(
                {"_id": user_id},
                {
                    "$pull": {"group_ids": chat_id},
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )
            return True
        except Exception:
            return False

    async def get_connected_groups(self, user_id: int) -> List[int]:
        c = self._conn_coll()
        if c is None:
            return []
        try:
            doc = await c.find_one({"_id": user_id})
            return list((doc or {}).get("group_ids") or [])
        except Exception:
            return []


config_manager = GroupConfigManager()
