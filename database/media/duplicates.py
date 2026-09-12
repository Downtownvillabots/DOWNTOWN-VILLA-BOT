"""
Duplicate detection for indexing.
Level 1: Telegram file_unique_id / file_id (exact)
Level 2: logical release identity (title + quality + codec + audio + ...)
Never uses file size as a duplicate key.
"""
import logging
from typing import Any, Dict, Optional

from database import db_registry

logger = logging.getLogger(__name__)


class DuplicateChecker:
    @staticmethod
    async def find_exact(db, file_unique_id: Optional[str],
                         file_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Return the existing record if exact Telegram identity matches."""
        query = None
        if file_unique_id:
            query = {"file_unique_id": file_unique_id}
        elif file_id:
            query = {"file_id": file_id}
        if not query:
            return None
        try:
            return await db["media_files"].find_one(query)
        except Exception as e:
            logger.warning(f"Exact duplicate check failed: {e}")
            return None

    @staticmethod
    def logical_identity(record: Dict[str, Any]) -> Optional[str]:
        """
        Build a stable identity string for logical release matching.
        Returns None if required fields are missing.
        """
        t = record.get("type")
        if t == "series":
            title = record.get("normalized_series_title")
            season = record.get("season")
            episode = record.get("episode")
            if not title or season is None or episode is None:
                return None
            parts = [title, f"S{season:02d}E{episode:02d}"]
        elif t == "movie":
            title = record.get("normalized_title")
            year = record.get("year")
            if not title:
                return None
            parts = [title, str(year) if year else ""]
        else:
            return None

        for k in ("quality", "codec", "source"):
            v = record.get(k)
            if v:
                parts.append(str(v))
        for lang in sorted(record.get("audio_languages") or []):
            parts.append(f"a:{lang}")
        for lang in sorted(record.get("subtitle_languages") or []):
            parts.append(f"s:{lang}")
        return "|".join(p for p in parts if p)

    @staticmethod
    async def find_logical(db, record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        identity = DuplicateChecker.logical_identity(record)
        if not identity:
            return None
        try:
            return await db["media_files"].find_one({"logical_identity": identity})
        except Exception as e:
            logger.warning(f"Logical duplicate check failed: {e}")
            return None

    @staticmethod
    async def check_all(record: Dict[str, Any]):
        """
        Try exact match across ALL media shards first, then logical.
        Returns (existing_record, shard_index) or (None, None).
        """
        entries = db_registry.media_entries()
        # Exact
        for entry in entries:
            found = await DuplicateChecker.find_exact(
                entry.db, record.get("file_unique_id"), record.get("file_id")
            )
            if found:
                return found, entry.index
        # Logical
        for entry in entries:
            found = await DuplicateChecker.find_logical(entry.db, record)
            if found:
                return found, entry.index
        return None, None


duplicate_checker = DuplicateChecker()
