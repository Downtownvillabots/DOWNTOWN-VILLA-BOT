"""
Group Statistics Manager.
Bounded per-day counters. Auto-resets at UTC midnight.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from database import db_registry

logger = logging.getLogger(__name__)


def _utc_midnight_ts() -> float:
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


class GroupStatisticsManager:
    def _coll(self):
        db = db_registry.get_user_db()
        return db["group_statistics"] if db is not None else None

    async def ensure_indexes(self) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.create_index("_id")
            await c.create_index("updated_at")
        except Exception:
            pass

    async def _ensure_doc(self, chat_id: int) -> None:
        c = self._coll()
        if c is None:
            return
        today = _utc_midnight_ts()
        try:
            await c.update_one(
                {"_id": chat_id},
                {"$setOnInsert": {
                    "searches_today": 0,
                    "movie_searches": 0,
                    "series_searches": 0,
                    "results_found": 0,
                    "not_found": 0,
                    "files_sent": 0,
                    "requests": 0,
                    "top_search": "",
                    "top_language": "",
                    "top_quality": "",
                    "search_counter": {},
                    "language_counter": {},
                    "quality_counter": {},
                    "daily_reset_at": today,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }},
                upsert=True,
            )
        except Exception:
            pass

    async def _maybe_reset_daily(self, chat_id: int) -> None:
        c = self._coll()
        if c is None:
            return
        today = _utc_midnight_ts()
        try:
            doc = await c.find_one({"_id": chat_id})
            if doc and doc.get("daily_reset_at", 0) < today:
                await c.update_one(
                    {"_id": chat_id},
                    {"$set": {
                        "searches_today": 0,
                        "movie_searches": 0,
                        "series_searches": 0,
                        "results_found": 0,
                        "not_found": 0,
                        "files_sent": 0,
                        "requests": 0,
                        "search_counter": {},
                        "language_counter": {},
                        "quality_counter": {},
                        "daily_reset_at": today,
                        "updated_at": time.time(),
                    }},
                )
        except Exception:
            pass

    async def increment(self, chat_id: int, key: str, amount: int = 1) -> None:
        c = self._coll()
        if c is None:
            return
        await self._ensure_doc(chat_id)
        try:
            await c.update_one(
                {"_id": chat_id},
                {"$inc": {key: amount}, "$set": {"updated_at": time.time()}},
            )
        except Exception:
            pass

    async def track_search(self, chat_id: int, query: str, kind: str = "movie",
                           language: Optional[str] = None,
                           quality: Optional[str] = None,
                           found: bool = False) -> None:
        """Update top counters. Bounded — only keeps top search/lang/quality."""
        c = self._coll()
        if c is None:
            return
        await self._ensure_doc(chat_id)
        await self._maybe_reset_daily(chat_id)

        inc = {"searches_today": 1, "updated_at": time.time()}
        if kind == "movie":
            inc["movie_searches"] = 1
        elif kind == "series":
            inc["series_searches"] = 1
        if found:
            inc["results_found"] = 1
        else:
            inc["not_found"] = 1

        # Track counters (capped to 50 unique)
        set_fields = {}
        if query:
            q_key = f"search_counter.{query.lower()[:32]}"
            set_fields[q_key] = None  # placeholder
        if language:
            set_fields[f"language_counter.{language.lower()[:16]}"] = None
        if quality:
            set_fields[f"quality_counter.{quality.upper()[:8]}"] = None

        update: Dict[str, Any] = {"$inc": inc}
        # Increment nested counters
        nested_inc: Dict[str, int] = {}
        if query:
            nested_inc[f"search_counter.{query.lower()[:32]}"] = 1
        if language:
            nested_inc[f"language_counter.{language.lower()[:16]}"] = 1
        if quality:
            nested_inc[f"quality_counter.{quality.upper()[:8]}"] = 1
        if nested_inc:
            update["$inc"] = {**inc, **nested_inc}

        try:
            await c.update_one({"_id": chat_id}, update)
            await self._refresh_tops(chat_id)
        except Exception:
            pass

    async def _refresh_tops(self, chat_id: int) -> None:
        """Recompute top_search/language/quality from counter dicts."""
        c = self._coll()
        if c is None:
            return
        try:
            doc = await c.find_one({"_id": chat_id})
            if not doc:
                return
            search_counter = doc.get("search_counter", {}) or {}
            lang_counter = doc.get("language_counter", {}) or {}
            qual_counter = doc.get("quality_counter", {}) or {}

            updates = {}
            if search_counter:
                top = max(search_counter.items(), key=lambda kv: kv[1])[0]
                updates["top_search"] = top
            if lang_counter:
                top = max(lang_counter.items(), key=lambda kv: kv[1])[0]
                updates["top_language"] = top
            if qual_counter:
                top = max(qual_counter.items(), key=lambda kv: kv[1])[0]
                updates["top_quality"] = top
            if updates:
                await c.update_one({"_id": chat_id}, {"$set": updates})
        except Exception:
            pass

    async def get_stats(self, chat_id: int) -> Dict[str, Any]:
        c = self._coll()
        if c is None:
            return {}
        await self._maybe_reset_daily(chat_id)
        try:
            doc = await c.find_one({"_id": chat_id}) or {}
            doc.pop("_id", None)
            doc.pop("search_counter", None)
            doc.pop("language_counter", None)
            doc.pop("quality_counter", None)
            return doc
        except Exception:
            return {}

    async def reset(self, chat_id: int) -> None:
        c = self._coll()
        if c is None:
            return
        try:
            await c.delete_one({"_id": chat_id})
        except Exception:
            pass


statistics_manager = GroupStatisticsManager()
