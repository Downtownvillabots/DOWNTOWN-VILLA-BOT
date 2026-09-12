"""
🎬 DOWNTOWN VILLA — IMDb service.
Single IMDBKit instance + get_poster() with bulk/id modes.
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from core.config import MAX_LIST_ELM

logger = logging.getLogger(__name__)

try:
    from imdbkit import IMDBKit
    imdb = IMDBKit()
    _HAS_IMDBKIT = True
    logger.info("[IMDB] IMDBKit loaded")
except Exception as e:
    imdb = None
    _HAS_IMDBKIT = False
    logger.warning(f"[IMDB] IMDBKit unavailable: {type(e).__name__}: {e}")


def is_available() -> bool:
    return _HAS_IMDBKIT


def _clean(q: str) -> str:
    if not q:
        return ""
    q = q.strip()
    q = re.sub(r"@\w+", "", q)
    q = re.sub(r"https?://\S+", "", q)
    return re.sub(r"\s+", " ", q).strip()


def _year_from(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.findall(r"[12]\d{3}", text)
    return m[-1] if m else None


async def get_poster(query: str = "", bulk: bool = False,
                     id: Optional[str] = None,
                     file: Optional[str] = None) -> Any:
    """
    bulk=True → list of brief dicts: [{title, year, imdb_id, kind}]
    id set    → full details dict
    else      → search, take first, return full details
    """
    if not _HAS_IMDBKIT:
        return [] if bulk else None

    # ── By IMDb id ──
    if id:
        try:
            movie = await asyncio.to_thread(imdb.get_movie, id)
        except Exception as e:
            logger.warning(f"[IMDB] get_movie failed: {e}")
            return None
        if not movie:
            return None
        return _to_details(movie, id)

    if not query:
        return [] if bulk else None

    q = _clean(query)
    year_val = _year_from(q) if not file else (_year_from(q) or _year_from(file))
    title = q
    if year_val:
        title = re.sub(rf"\b{year_val}\b", "", q).strip() or q

    # ── Search ──
    try:
        result = await asyncio.to_thread(imdb.search_movie, title.lower())
    except Exception as e:
        logger.warning(f"[IMDB] search_movie failed: {e}")
        return [] if bulk else None

    titles = getattr(result, "titles", None) if result else None
    if not titles:
        return [] if bulk else None

    # ── Build brief list ──
    briefs: List[Dict[str, Any]] = []
    for m in titles:
        t = getattr(m, "title", None)
        if not t:
            continue
        briefs.append({
            "title": t,
            "year": getattr(m, "year", None),
            "imdb_id": getattr(m, "imdb_id", None),
            "kind": getattr(m, "kind", None),
        })

    # ── Filter by year ──
    if year_val:
        by_year = [b for b in briefs if str(b.get("year") or "") == str(year_val)]
        if by_year:
            briefs = by_year

    # ── Filter by kind ──
    good_kinds = {"movie", "tv series", "tvseriess", "tvminiseries", "tvmovie"}
    by_kind = [b for b in briefs if (b.get("kind") or "").lower() in good_kinds]
    if by_kind:
        briefs = by_kind

    # ── Cap ──
    if MAX_LIST_ELM:
        briefs = briefs[:MAX_LIST_ELM]

    if bulk:
        return briefs

    if not briefs:
        return None

    # ── Fetch details of first result ──
    first_id = briefs[0].get("imdb_id")
    if not first_id:
        return None
    return await get_poster(id=first_id)


def _to_details(movie, imdb_id: str) -> Dict[str, Any]:
    def _names(v):
        if not v:
            return []
        out = []
        for item in v:
            name = getattr(item, "name", None) or str(item)
            if name:
                out.append(name)
        return out

    plot = getattr(movie, "plot", None)
    if isinstance(plot, list):
        plot_text = plot[0] if plot else ""
    else:
        plot_text = plot or ""
    if len(plot_text) > 800:
        plot_text = plot_text[:800] + "..."

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
        "cast": _names(getattr(movie, "cast", [])),
        "directors": _names(getattr(movie, "directors", [])),
        "writers": _names(getattr(movie, "writers", [])),
        "languages": list(getattr(movie, "languages", []) or []),
        "countries": list(getattr(movie, "countries", []) or []),
        "certificates": list(getattr(movie, "certificates", []) or []),
        "duration": duration,
        "release_date": getattr(movie, "release_date", None),
        "kind": getattr(movie, "kind", None),
        "source": "imdb",
    }
