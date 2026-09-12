"""
Parallel media search engine.
Searches ALL configured shards concurrently with timeout + failure awareness.
Never claims "not found" if a shard failed.
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from media_search.config import (
    SHARD_TIMEOUT, SHARD_CONCURRENCY, MAX_SEARCH_RESULTS,
)
from media_search.models import FileHit, SearchResult
from media_search.normalizer import normalize
from media_search.registry import media_registry

logger = logging.getLogger(__name__)

# Fields to fetch — never load full docs
_PROJECTION = {
    "_id": 0,
    "file_id": 1,
    "file_unique_id": 1,
    "file_name": 1,
    "file_size": 1,
    "title": 1,
    "normalized_title": 1,
    "year": 1,
    "type": 1,
    "quality": 1,
    "codec": 1,
    "source": 1,
    "audio_languages": 1,
    "subtitle_languages": 1,
    "has_subtitle": 1,
    "series_title": 1,
    "normalized_series_title": 1,
    "season": 1,
    "episode": 1,
    "episode_identifier": 1,
    "channel_id": 1,
    "message_id": 1,
    "caption": 1,
}


def _regex_safe(s: str) -> str:
    return re.escape(s)


class SearchEngine:
    """Search engine across all media shards."""

    # ────────── Public API ──────────
    async def search_movie(self, query: str, year: Optional[int] = None,
                           limit: int = MAX_SEARCH_RESULTS) -> SearchResult:
        """Find all movie files matching a normalized title."""
        norm = normalize(query)
        if not norm:
            return SearchResult(hits=[], complete=True)

        mongo_query = self._build_movie_query(norm, year)
        return await self._search_all_shards(mongo_query, limit)

    async def search_series(self, query: str, year: Optional[int] = None,
                            season: Optional[int] = None,
                            episode: Optional[int] = None,
                            limit: int = MAX_SEARCH_RESULTS) -> SearchResult:
        """Find series files. Optional season/episode narrowing."""
        norm = normalize(query)
        if not norm:
            return SearchResult(hits=[], complete=True)

        mongo_query = self._build_series_query(norm, year, season, episode)
        return await self._search_all_shards(mongo_query, limit)

    async def search_any(self, query: str, year: Optional[int] = None,
                         limit: int = MAX_SEARCH_RESULTS) -> SearchResult:
        """Find all files (movie OR series) matching a title."""
        norm = normalize(query)
        if not norm:
            return SearchResult(hits=[], complete=True)

        mongo_query = self._build_any_query(norm, year)
        return await self._search_all_shards(mongo_query, limit)

    async def availability(self, normalized_title: str) -> Dict[str, Any]:
        """
        Return available languages / qualities / seasons / episodes
        for a normalized title without fetching full documents.
        """
        # Fetch only the fields we need for aggregation
        mongo_query = {"normalized_title": normalized_title}
        result = await self._search_all_shards(mongo_query, MAX_SEARCH_RESULTS)

        languages: Set[str] = set()
        qualities: Set[str] = set()
        seasons: Set[int] = set()
        episodes: Set[Tuple[int, int]] = set()
        years: Set[int] = set()

        for h in result.hits:
            languages.update(h.audio_languages or [])
            if h.quality:
                qualities.add(h.quality)
            if h.year:
                years.add(h.year)
            if h.season is not None:
                seasons.add(h.season)
                if h.episode is not None:
                    episodes.add((h.season, h.episode))

        return {
            "languages": sorted(languages),
            "qualities": self._sort_qualities(qualities),
            "years": sorted(years),
            "seasons": sorted(seasons),
            "episodes": sorted(episodes),
            "hit_count": len(result.hits),
            "complete": result.complete,
            "failed_shards": result.failed_shards,
        }

    # ────────── Query builders ──────────
    def _build_movie_query(self, norm: str, year: Optional[int]) -> Dict[str, Any]:
        q: Dict[str, Any] = {
            "type": "movie",
            "$or": [
                {"normalized_title": norm},
                {"normalized_title": {"$regex": f"^{_regex_safe(norm)}\\b"}},
            ],
        }
        if year:
            q["year"] = year
        return q

    def _build_series_query(self, norm: str, year: Optional[int],
                            season: Optional[int], episode: Optional[int]) -> Dict[str, Any]:
        q: Dict[str, Any] = {
            "type": "series",
            "$or": [
                {"normalized_series_title": norm},
                {"normalized_series_title": {"$regex": f"^{_regex_safe(norm)}\\b"}},
                {"normalized_title": norm},
            ],
        }
        if year:
            q["year"] = year
        if season is not None:
            q["season"] = season
        if episode is not None:
            q["episode"] = episode
        return q

    def _build_any_query(self, norm: str, year: Optional[int]) -> Dict[str, Any]:
        q: Dict[str, Any] = {
            "$or": [
                {"normalized_title": norm},
                {"normalized_title": {"$regex": f"^{_regex_safe(norm)}\\b"}},
                {"normalized_series_title": norm},
                {"normalized_series_title": {"$regex": f"^{_regex_safe(norm)}\\b"}},
            ],
        }
        if year:
            q["year"] = year
        return q

    # ────────── Core search ──────────
    async def _search_all_shards(self, mongo_query: Dict[str, Any],
                                 limit: int) -> SearchResult:
        entries = media_registry.all_shards()
        if not entries:
            return SearchResult(hits=[], complete=False, failed_shards=[])

        started = time.time()
        sem = asyncio.Semaphore(SHARD_CONCURRENCY)
        tasks = [
            self._search_one_shard(e, mongo_query, limit, sem)
            for e in entries
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        hits: List[FileHit] = []
        failed: List[int] = []
        for idx, (shard_index, shard_hits, ok) in enumerate(results):
            if not ok:
                failed.append(shard_index)
                continue
            hits.extend(shard_hits)

        # Dedupe by file_unique_id, else by file_id
        hits = self._dedupe(hits)

        # Rank and cap
        hits = self._rank(hits)[:limit]

        return SearchResult(
            hits=hits,
            complete=(len(failed) == 0),
            failed_shards=failed,
            elapsed_ms=(time.time() - started) * 1000.0,
        )

    async def _search_one_shard(self, entry, mongo_query: Dict[str, Any],
                                limit: int, sem: asyncio.Semaphore
                                ) -> Tuple[int, List[FileHit], bool]:
        async with sem:
            try:
                cursor = (
                    entry.db["media_files"]
                    .find(mongo_query, _PROJECTION)
                    .limit(limit)
                )
                docs = await asyncio.wait_for(
                    cursor.to_list(length=limit),
                    timeout=SHARD_TIMEOUT,
                )
                hits = [FileHit.from_mongo(d, entry.index) for d in docs]
                return (entry.index, hits, True)
            except asyncio.TimeoutError:
                logger.warning(f"[SEARCH] shard {entry.index:02d} timed out")
                return (entry.index, [], False)
            except Exception as e:
                logger.warning(f"[SEARCH] shard {entry.index:02d} failed: {e}")
                return (entry.index, [], False)

    # ────────── Post-processing ──────────
    def _dedupe(self, hits: List[FileHit]) -> List[FileHit]:
        """Exact dedupe by file_unique_id (fallback file_id)."""
        seen: Set[str] = set()
        out: List[FileHit] = []
        for h in hits:
            key = h.file_unique_id or h.file_id
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
        return out

    def _rank(self, hits: List[FileHit]) -> List[FileHit]:
        """Order: preferred quality, then codec, then largest file."""
        from media_search.config import PREFERRED_QUALITY, PREFERRED_CODEC

        def _score(h: FileHit) -> Tuple:
            q_rank = 0 if (h.quality or "").lower() == PREFERRED_QUALITY.lower() else 1
            c_rank = 0 if (h.codec or "").upper() == PREFERRED_CODEC.upper() else 1
            size = -(h.file_size or 0)
            return (q_rank, c_rank, size)

        return sorted(hits, key=_score)

    def _sort_qualities(self, qualities: Set[str]) -> List[str]:
        from media_search.config import QUALITIES
        order = {q.upper(): i for i, q in enumerate(QUALITIES)}
        return sorted(qualities, key=lambda q: order.get(q.upper(), 999))


engine = SearchEngine()
