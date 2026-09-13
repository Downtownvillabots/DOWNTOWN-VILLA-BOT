"""
DOWNTOWN VILLA — Unified Metadata Service.
TMDB → OMDb → IMDb fallback chain + Mongo cache.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from database import db_registry

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 30
NEGATIVE_TTL_HOURS = 6
MAX_CONCURRENCY = 5

_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

# In-memory L1 cache
_L1: Dict[str, tuple] = {}
_L1_MAX = 500
_L1_TTL = 3600
_ttl_index_created = False


def _cache_key(query: str, **kwargs) -> str:
    parts = [(query or "").strip().lower()]
    for k in sorted(kwargs):
        v = kwargs[k]
        if v is not None:
            parts.append(f"{k}={v}")
    return "|".join(parts)


def _l1_get(key: str):
    e = _L1.get(key)
    if not e:
        return None
    v, exp = e
    if time.time() > exp:
        _L1.pop(key, None)
        return None
    return v


def _l1_set(key: str, value):
    if len(_L1) >= _L1_MAX:
        oldest = min(_L1, key=lambda k: _L1[k][1])
        _L1.pop(oldest, None)
    _L1[key] = (value, time.time() + _L1_TTL)


async def _l2_get(key: str) -> Optional[Any]:
    db = db_registry.get_system_db()
    if db is None:
        return None
    try:
        doc = await db["metadata_cache"].find_one({"_id": key})
        if not doc:
            return None
        exp = doc.get("expires_at")
        if isinstance(exp, datetime) and exp < datetime.utcnow():
            await db["metadata_cache"].delete_one({"_id": key})
            return None
        v = doc.get("value")
        if isinstance(v, dict) and v.get("__nf__"):
            return None
        return v
    except Exception as e:
        logger.debug(f"[META] L2 read failed: {e}")
        return None


async def _l2_set(key: str, value, ttl_days: int = None, ttl_hours: int = None):
    db = db_registry.get_system_db()
    if db is None:
        return
    try:
        exp = datetime.utcnow() + (
            timedelta(hours=ttl_hours) if ttl_hours else
            timedelta(days=ttl_days or CACHE_TTL_DAYS)
        )
        await db["metadata_cache"].update_one(
            {"_id": key},
            {"$set": {"value": value, "expires_at": exp, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        global _ttl_index_created
        if not _ttl_index_created:
            try:
                await db["metadata_cache"].create_index("expires_at", expireAfterSeconds=0)
                _ttl_index_created = True
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[META] L2 write failed: {e}")


# ═══════════════════════ PUBLIC API ═══════════════════════
async def get_metadata(query: str, bulk: bool = False,
                       id: Optional[str] = None,
                       file: Optional[str] = None) -> Any:
    """Fetch metadata with caching + provider fallback."""
    if not query and not id:
        return [] if bulk else None

    key = _cache_key(query or id or "", bulk=bulk, id=bool(id), file=file)

    cached = _l1_get(key)
    if cached is not None:
        return cached

    l2 = await _l2_get(key)
    if l2 is not None:
        _l1_set(key, l2)
        return l2

    async with _semaphore:
        result = await _fetch_chain(query, bulk=bulk, id=id, file=file)

    if result is not None:
        await _l2_set(key, result, ttl_days=CACHE_TTL_DAYS)
        _l1_set(key, result)
    else:
        await _l2_set(key, {"__nf__": True}, ttl_hours=NEGATIVE_TTL_HOURS)

    return result


async def _fetch_chain(query, bulk, id, file):
    from services.providers import tmdb_provider, omdb_provider, imdb_provider

    providers = [
        ("tmdb", tmdb_provider.fetch),
        ("omdb", omdb_provider.fetch),
        ("imdb", imdb_provider.fetch),
    ]
    for name, fn in providers:
        try:
            r = await fn(query, bulk=bulk, id=id, file=file)
            if r:
                logger.info(f"[META] got from {name}: {query!r}")
                return r
        except Exception as e:
            logger.warning(f"[META] {name} failed: {e}")
    logger.info(f"[META] no result from any provider: {query!r}")
    return None


# ═══════════════════════ COMPAT WRAPPERS ═══════════════════════
async def get_poster(query: str = "", bulk: bool = False,
                     id: Optional[str] = None,
                     file: Optional[str] = None):
    """Compat wrapper matching services.imdb.get_poster() shape."""
    if bulk:
        r = await get_metadata(query, bulk=True)
        # Return raw list of briefs (dict form)
        if isinstance(r, list):
            return [
                {"title": b.get("title"), "year": b.get("year"),
                 "imdb_id": b.get("imdb_id"), "kind": b.get("kind")}
                for b in r
            ]
        return []
    return await get_metadata(query, id=id, file=file)


def is_available() -> bool:
    """True if any provider is configured."""
    from core.config import TMDB_API_KEY, OMDB_API_KEY
    from services import imdb as _imdb
    return bool(TMDB_API_KEY or OMDB_API_KEY or _imdb.is_available())
