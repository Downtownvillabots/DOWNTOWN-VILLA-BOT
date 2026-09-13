"""OMDb provider — free-tier fallback. Env: OMDB_API_KEY"""
import logging
from typing import Optional, Dict, Any
import aiohttp
from core.config import OMDB_API_KEY

logger = logging.getLogger(__name__)
OMDB_BASE = "http://www.omdbapi.com/"


async def fetch(query: str, bulk: bool = False,
                id: Optional[str] = None,
                file: Optional[str] = None):
    if not OMDB_API_KEY:
        return None
    params = {"apikey": OMDB_API_KEY, "plot": "full", "r": "json"}
    params["i" if id else "t"] = query
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(OMDB_BASE, params=params, timeout=10) as r:
                data = await r.json()
    except Exception as e:
        logger.warning(f"[OMDB] fetch failed: {e}")
        return None
    if data.get("Response") != "True":
        return None

    poster = data.get("Poster")
    if poster == "N/A":
        poster = None
    return {
        "source": "omdb",
        "imdb_id": data.get("imdbID"),
        "title": data.get("Title"),
        "year": int((data.get("Year") or "0000")[:4] or 0) or None,
        "rating": data.get("imdbRating"),
        "runtime": data.get("Runtime") if data.get("Runtime") != "N/A" else None,
        "genres": [g.strip() for g in (data.get("Genre") or "").split(",") if g.strip()],
        "languages": [l.strip() for l in (data.get("Language") or "").split(",") if l.strip()],
        "countries": [c.strip() for c in (data.get("Country") or "").split(",") if c.strip()],
        "director": [d.strip() for d in (data.get("Director") or "").split(",") if d.strip()],
        "cast": [c.strip() for c in (data.get("Actors") or "").split(",") if c.strip()],
        "plot": data.get("Plot") if data.get("Plot") != "N/A" else None,
        "poster_url": poster,
        "poster": poster,
        "certificates": data.get("Rated") if data.get("Rated") != "N/A" else None,
        "url": f"https://www.imdb.com/title/{data.get('imdbID')}",
        "kind": "movie" if data.get("Type") == "movie" else "tv series",
    }
