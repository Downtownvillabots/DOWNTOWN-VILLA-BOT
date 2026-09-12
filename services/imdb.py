"""
🎬 DOWNTOWN VILLA — IMDb service.
IMDBKit singleton + get_poster() + search_movie() + get_movie().
Mirrors the old bot's utils.py behavior.

Fallback chain:
  1. IMDBKit (from git) — no API key needed
  2. TMDB (via media_search.metadata) — if IMDBKit fails
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from core.config import MAX_LIST_ELM

logger = logging.getLogger(__name__)

# ═══════════════════════ IMDBKit SINGLETON ═══════════════════════
try:
    from imdbkit import IMDBKit  # type: ignore
    imdb = IMDBKit()
    _HAS_IMDBKIT = True
    logger.info("[IMDB] IMDBKit loaded")
except Exception as e:
    imdb = None
    _HAS_IMDBKIT = False
    logger.warning(f"[IMDB] IMDBKit unavailable: {type(e).__name__}: {e}")


# ═══════════════════════ HELPERS ═══════════════════════
def _clean_query(q: str) -> str:
    """Strip punctuation noise from a query."""
    if not q:
        return ""
    q = q.strip()
    q = re.sub(r"@\w+", "", q)          # @mentions
    q = re.sub(r"https?://\S+", "", q)  # URLs
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_year(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.findall(r"[12]\d{3}", text)
    return m[-1] if m else None


# ═══════════════════════ SEARCH (brief) ═══════════════════════
async def search_titles(query: str) -> List[Dict[str, Any]]:
    """
    Return a list of brief movie/tv titles from IMDb.
    Shape: [{title, year, imdb_id, kind}, ...]
    Empty list if IMDBKit unavailable or no matches.
    """
    if not _HAS_IMDBKIT or not query:
        return []

    q = _clean_query(query)
    if not q:
        return []

    try:
        result = await asyncio.to_thread(imdb.search_movie, q.lower())
    except Exception as e:
        logger.warning(f"[IMDB] search_movie failed: {type(e).__name__}: {e}")
        return []

    if not result or not getattr(result, "titles", None):
        return []

    out: List[Dict[str, Any]] = []
    for m in result.titles:
        title = getattr(m, "title", None)
        if not title:
            continue
        out.append({
            "title": title,
            "year": getattr(m, "year", None),
            "imdb_id": getattr(m, "imdb_id", None),
            "kind": getattr(m, "kind", None),
        })
    return out


# ═══════════════════════ DETAILS (full) ═══════════════════════
async def get_movie_details(imdb_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch full details for an IMDb id.
    Shape mirrors the old bot's get_poster output.
    """
    if not _HAS_IMDBKIT or not imdb_id:
        return None
    try:
        movie = await asyncio.to_thread(imdb.get_movie, imdb_id)
    except Exception as e:
        logger.warning(f"[IMDB] get_movie failed: {type(e).__name__}: {e}")
        return None
    if not movie:
        return None

    def _str_list(v) -> List[str]:
        if not v:
            return []
        if isinstance(v, str):
            return [v]
        out = []
        for item in v:
            name = getattr(item, "name", None) or str(item)
            if name:
                out.append(name)
        return out

    plot = movie.plot if isinstance(getattr(movie, "plot", None), list) else [
        getattr(movie, "plot", "")
    ]
    plot_text = plot[0] if plot else ""
    duration = getattr(movie, "duration", None)
    if isinstance(duration, list):
        duration = duration[0] if duration else None

    return {
        "imdb_id": imdb_id,
        "title": getattr(movie, "title", "") or "",
        "year": getattr(movie, "year", None),
        "rating": getattr(movie, "rating", None),
        "votes": getattr(movie, "votes", None),
        "genres": list(getattr(movie, "genres", []) or []),
        "plot": plot_text,
        "poster": getattr(movie, "cover_url", None),
        "url": getattr(movie, "url", None),
        "cast": _str_list(getattr(movie, "cast", [])),
        "directors": _str_list(getattr(movie, "directors", [])),
        "writers": _str_list(getattr(movie, "writers", [])),
        "languages": list(getattr(movie, "languages", []) or []),
        "countries": list(getattr(movie, "countries", []) or []),
        "certificates": list(getattr(movie, "certificates", []) or []),
        "duration": duration,
        "release_date": getattr(movie, "release_date", None),
        "kind": getattr(movie, "kind", None),
        "source": "imdb",
    }


# ═══════════════════════ GET_POSTER (old-bot style) ═══════════════════════
async def get_poster(query: str, bulk: bool = False,
                     id: Optional[str] = None,
                     file: Optional[str] = None) -> Any:
    """
    Old-bot-compatible get_poster.
      bulk=True  → return list of brief movies (for suggestion picker)
      id set     → fetch full details by IMDb id
      else       → search, take first result, fetch full details
    """
    if not _HAS_IMDBKIT:
        return None if not bulk else []

    # ── By ID ──
    if id:
        return await get_movie_details(id)

    if not query:
        return None if not bulk else []

    # Extract year from query if present
    q = _clean_query(query)
    year_val = _extract_year(q)
    title = q
    if year_val:
        title = re.sub(rf"\b{year_val}\b", "", q).strip()

    briefs = await search_titles(title.lower())
    if not briefs:
        return None if not bulk else []

    # Filter by year if provided
    if year_val:
        by_year = [b for b in briefs if str(b.get("year") or "") == str(year_val)]
        if by_year:
            briefs = by_year

    # Filter by kind (movie/tv)
    kind_filter = {"movie", "tv series", "tvseriess", "tvminiseries", "tvmovie"}
    by_kind = [b for b in briefs if (b.get("kind") or "").lower() in kind_filter]
    if by_kind:
        briefs = by_kind

    # Cap list
    if MAX_LIST_ELM:
        briefs = briefs[:MAX_LIST_ELM]

    # Bulk mode → return the briefs
    if bulk:
        return briefs

    # Non-bulk → fetch full details of first result
    if not briefs:
        return None
    first = briefs[0]
    imdb_id = first.get("imdb_id")
    if not imdb_id:
        return None
    return await get_movie_details(imdb_id)


# ═══════════════════════ DIAGNOSTICS ═══════════════════════
def is_available() -> bool:
    return _HAS_IMDBKIT
