# services/settings_service.py
"""
DOWNTOWN VILLA — Per-group settings service.

Wraps the `groups` collection. Cached in memory for fast lookups.
Compatible with old API: get_settings() / save_group_settings()
"""

import time
import logging
from datetime import datetime
from typing import Any, Dict

from database import db_manager

logger = logging.getLogger(__name__)
logger.info("[SETTINGS-SERVICE] module loaded")


DEFAULTS: Dict[str, Any] = {
    "button": False,
    "botpm": False,
    "file_secure": False,
    "imdb": True,
    "spell_check": True,
    "welcome": False,
    "auto_delete": True,
    "auto_ffilter": True,
    "max_btn": True,
    "is_verify": False,
    "template": None,
    "caption": None,
    "log": None,
    "fsub": [],
    "verify_time": 1200,
    "third_verify_time": 54000,
    "tutorial": None,
    "tutorial_2": None,
    "tutorial_3": None,
}

# ── Cache ──
_CACHE: Dict[int, Dict[str, Any]] = {}
_CACHE_TS: Dict[int, float] = {}
_CACHE_TTL = 300


def _cache_get(chat_id: int):
    ts = _CACHE_TS.get(chat_id)
    if not ts or time.time() - ts > _CACHE_TTL:
        _CACHE.pop(chat_id, None)
        _CACHE_TS.pop(chat_id, None)
        return None
    return _CACHE.get(chat_id)


def _cache_set(chat_id: int, value: Dict[str, Any]):
    _CACHE[chat_id] = value
    _CACHE_TS[chat_id] = time.time()


def _cache_invalidate(chat_id: int):
    _CACHE.pop(chat_id, None)
    _CACHE_TS.pop(chat_id, None)


def _groups_coll():
    """Return groups collection from whichever DB db_manager exposes."""
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                db = fn()
                if db is not None:
                    return db["groups"]
    except Exception:
        pass
    return None


async def get_settings(chat_id: int) -> Dict[str, Any]:
    """Return full settings with defaults merged."""
    chat_id = int(chat_id)
    cached = _cache_get(chat_id)
    if cached is not None:
        return cached

    coll = _groups_coll()
    if coll is None:
        return dict(DEFAULTS)

    try:
        doc = await coll.find_one({"chat_id": chat_id})
    except Exception as e:
        logger.warning(f"[SETTINGS] read failed {chat_id}: {e}")
        return dict(DEFAULTS)

    merged = dict(DEFAULTS)
    if doc:
        sub = doc.get("settings") or {}
        if isinstance(sub, dict):
            merged.update(sub)
        for k in DEFAULTS.keys():
            if k in doc and doc[k] is not None:
                merged[k] = doc[k]

    _cache_set(chat_id, merged)
    return merged


async def save_group_settings(chat_id: int, key: str, value: Any) -> bool:
    """Atomically set one field (top-level and inside `settings`)."""
    chat_id = int(chat_id)
    coll = _groups_coll()
    if coll is None:
        return False

    try:
        await coll.update_one(
            {"chat_id": chat_id},
            {
                "$set": {
                    f"settings.{key}": value,
                    key: value,
                    "updated_at": datetime.utcnow(),
                },
                "$setOnInsert": {
                    "chat_id": chat_id,
                    "created_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )
        _cache_invalidate(chat_id)
        return True
    except Exception as e:
        logger.warning(f"[SETTINGS] save failed {chat_id}/{key}: {e}")
        return False


def invalidate_settings_cache(chat_id: int) -> None:
    _cache_invalidate(int(chat_id))
