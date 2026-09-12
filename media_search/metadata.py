"""
Metadata provider abstraction (TMDB primary).
Cached, timeout-protected, non-blocking. Falls back to indexed-only if down.
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

from media_search.config import (
    METADATA_API_KEY, METADATA_ENABLED, METADATA_PROVIDER,
    METADATA_TIMEOUT, METADATA_CACHE_TTL,
)

logger = logging.getLogger(__name__)


class _Cache:
    def __init__(self, ttl: int):
        self.ttl = ttl
        self._d: Dict[str, tuple] = {}

    def get(self, k: str):
        e = self._d.get(k)
        if not e:
            return None
        if time.time() - e[0] > self.ttl:
            self._d.pop(k, None)
            return None
        return e[1]

    def set(self, k: str, v: Any) -> None:
        self._d[k] = (time.time(), v)


cache = _Cache(METADATA_CACHE_TTL)


class MetadataProvider:
    """TMDB metadata fetch."""

    BASE = "https://api.themoviedb.org/3"
    IMG_BASE = "https://image.tmdb.org/t/p/w500"

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ────────── Public API ──────────
    async def search(self, query: str, year: Optional[int] = None,
                     is_series: bool = False) -> List[Dict[str, Any]]:
        """
        Return a list of candidate titles.
        Empty list if provider is disabled, unavailable, or returns nothing.
        """
        if not METADATA_ENABLED or not METADATA_API_KEY:
            return []

        cache_key = f"search:{query.lower()}:{year}:{is_series}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        endpoint = "search/tv" if is_series else "search/movie"
        params = {
            "api_key": METADATA_API_KEY,
            "query": query,
            "include_adult": "false",
        }
        if year:
            params["year"] = str(year)

        data = await self._fetch(endpoint, params)
        if not data:
            cache.set(cache_key, [])
            return []

        results = data.get("results", []) or []
        out = []
        for r in results[:10]:
            title = r.get("title") or r.get("name") or ""
            if not title:
                continue
            out.append({
                "metadata_id": str(r.get("id")),
                "metadata_source": "tmdb",
                "type": "series" if is_series else "movie",
                "title": title,
                "year": self._parse_year(r.get("release_date") or r.get("first_air_date")),
                "poster": (self.IMG_BASE + r["poster_path"]) if r.get("poster_path") else None,
                "overview": r.get("overview"),
                "rating": r.get("vote_average"),
            })
        cache.set(cache_key, out)
        return out

    async def details(self, metadata_id: str, is_series: bool = False) -> Optional[Dict[str, Any]]:
        """Fetch full details for a specific title."""
        if not METADATA_ENABLED or not METADATA_API_KEY:
            return None

        cache_key = f"details:{metadata_id}:{is_series}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        endpoint = f"tv/{metadata_id}" if is_series else f"movie/{metadata_id}"
        params = {"api_key": METADATA_API_KEY, "append_to_response": "external_ids"}

        data = await self._fetch(endpoint, params)
        if not data:
            return None

        genres = [g.get("name") for g in (data.get("genres") or []) if g.get("name")]
        languages = []
        if data.get("spoken_languages"):
            languages = [l.get("english_name") or l.get("name") for l in data["spoken_languages"]]

        details = {
            "metadata_id": metadata_id,
            "metadata_source": "tmdb",
            "type": "series" if is_series else "movie",
            "title": data.get("title") or data.get("name") or "",
            "year": self._parse_year(data.get("release_date") or data.get("first_air_date")),
            "poster": (self.IMG_BASE + data["poster_path"]) if data.get("poster_path") else None,
            "overview": data.get("overview"),
            "rating": data.get("vote_average"),
            "genres": genres,
            "languages": languages,
            "runtime": data.get("runtime") or data.get("episode_run_time", [None])[0] if data.get("episode_run_time") else None,
            "seasons": data.get("number_of_seasons"),
            "episodes": data.get("number_of_episodes"),
        }
        cache.set(cache_key, details)
        return details

    # ────────── Internals ──────────
    async def _fetch(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            session = await self._get_session()
            url = f"{self.BASE}/{endpoint}"
            async with session.get(url, params=params, timeout=METADATA_TIMEOUT) as resp:
                if resp.status != 200:
                    logger.warning(f"[META] {endpoint} HTTP {resp.status}")
                    return None
                return await resp.json()
        except asyncio.TimeoutError:
            logger.warning(f"[META] timeout on {endpoint}")
            return None
        except Exception as e:
            logger.warning(f"[META] fetch failed: {type(e).__name__}: {e}")
            return None

    @staticmethod
    def _parse_year(date_str: Optional[str]) -> Optional[int]:
        if not date_str:
            return None
        try:
            return int(date_str.split("-")[0])
        except (ValueError, IndexError):
            return None


metadata_provider = MetadataProvider()
