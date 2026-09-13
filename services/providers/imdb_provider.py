"""IMDb provider — uses IMDBKit (no API key). Last-resort fallback."""
import asyncio
import logging
from typing import Optional

from services import imdb as imdb_service

logger = logging.getLogger(__name__)


async def fetch(query: str, bulk: bool = False,
                id: Optional[str] = None,
                file: Optional[str] = None):
    if not imdb_service.is_available():
        return None
    try:
        if bulk:
            briefs = await imdb_service.get_poster(query, bulk=True)
            if not briefs:
                return []
            return [
                {"title": b.get("title"), "year": b.get("year"),
                 "imdb_id": b.get("imdb_id"), "kind": b.get("kind")}
                for b in briefs[:10]
            ]
        if id:
            return await imdb_service.get_poster(id=id)
        return await imdb_service.get_poster(query, file=file)
    except Exception as e:
        logger.warning(f"[IMDB] fetch failed: {e}")
        return None
