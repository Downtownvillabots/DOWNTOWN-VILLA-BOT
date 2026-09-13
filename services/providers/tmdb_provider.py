"""
TMDB provider — primary metadata source.
"""
import asyncio
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import aiohttp

from core.config import TMDB_API_KEY

logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/original"
TIMEOUT = 15
RETRIES = 3
MIN_RUNTIME = 40


async def _get(session, path: str, params: Optional[Dict] = None):
    if not TMDB_API_KEY:
        return None
    p = dict(params or {})
    p["api_key"] = TMDB_API_KEY
    url = f"{TMDB_BASE}/{path.lstrip('/')}"
    for attempt in range(RETRIES):
        try:
            async with session.get(url, params=p, timeout=TIMEOUT) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status != 200:
                    return None
                return await resp.json()
        except Exception as e:
            logger.debug(f"[TMDB] attempt {attempt+1} failed: {e}")
            if attempt == RETRIES - 1:
                return None
            await asyncio.sleep(1.5 ** attempt)


def _extract_title_year(query: str, file: Optional[str]):
    q = (query or "").strip().lower()
    m = re.search(r"\b(19|20)\d{2}\b", q)
    if m:
        return q.replace(m.group(0), "").strip(), int(m.group(0))
    if file:
        m = re.search(r"\b(19|20)\d{2}\b", file)
        if m:
            return q, int(m.group(0))
    return q, None


async def _best_match(session, query: str, file: Optional[str]):
    title, year = _extract_title_year(query, file)
    words = title.split()
    queries = [title]
    if len(words) > 2:
        queries += [" ".join(words[:-1]), words[0]]
    queries = list(dict.fromkeys(q for q in queries if q))[:3]

    results: List[Dict] = []
    for q in queries:
        data = await _get(session, "search/multi", {
            "query": q, "language": "en-US", "include_adult": "false",
        })
        if data and data.get("results"):
            results = data["results"]
            break
    if not results:
        return None

    scored = []
    for r in results:
        if r.get("media_type") not in ("movie", "tv"):
            continue
        t = (r.get("title") or r.get("name") or "")
        ratio = SequenceMatcher(None, t.lower(), title.lower()).ratio()
        rel = (r.get("release_date") or r.get("first_air_date") or "")[:4]
        year_ok = not year or (rel and abs(int(rel) - year) <= 1)
        if ratio >= 0.4 and year_ok:
            scored.append((r, ratio, r.get("popularity", 0)))

    if not scored:
        return None
    scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
    best = scored[0][0]
    return best.get("media_type"), best["id"]


async def _details(session, media_type: str, media_id: int) -> Optional[Dict]:
    return await _get(session, f"{media_type}/{media_id}", {
        "append_to_response":
            "credits,external_ids,alternative_titles,release_dates,images,videos",
    })


def _pick_poster(images: Dict, fallback_path: Optional[str]) -> Optional[str]:
    posters = (images or {}).get("posters", {})
    for lang in ("en", "xx", "no_lang"):
        if posters.get(lang):
            return posters[lang][0]
    if fallback_path:
        return f"{TMDB_IMG}{fallback_path}"
    return None


def _process_images(images: Dict) -> Dict:
    posters, backdrops = {}, {}
    for img in (images or {}).get("posters", []):
        lang = img.get("iso_639_1") or "no_lang"
        posters.setdefault(lang, []).append(f"{TMDB_IMG}{img['file_path']}")
    for img in (images or {}).get("backdrops", []):
        lang = img.get("iso_639_1") or "no_lang"
        backdrops.setdefault(lang, []).append(f"{TMDB_IMG}{img['file_path']}")
    return {"posters": posters, "backdrops": backdrops}


def _certifications(details: Dict) -> Optional[str]:
    rd = details.get("release_dates") or {}
    for country in rd.get("results", []):
        if country.get("iso_3166_1") == "US":
            for x in country.get("release_dates", []):
                if x.get("certification"):
                    return x["certification"]
    return None


def _normalize(details: Dict, media_type: str) -> Dict[str, Any]:
    crew = details.get("credits", {}).get("crew", []) or []
    cast = details.get("credits", {}).get("cast", []) or []
    images = _process_images(details.get("images", {}))
    release = details.get("release_date") or details.get("first_air_date") or ""

    return {
        "source": "tmdb",
        "tmdb_id": details.get("id"),
        "imdb_id": (details.get("external_ids") or {}).get("imdb_id"),
        "title": details.get("title") or details.get("name"),
        "localized_title": details.get("original_title") or details.get("original_name"),
        "year": int(release[:4]) if release[:4].isdigit() else None,
        "release_date": release,
        "rating": round(float(details.get("vote_average") or 0), 1),
        "votes": details.get("vote_count"),
        "genres": [g["name"] for g in details.get("genres", [])],
        "languages": [l.get("english_name") or l.get("name")
                       for l in details.get("spoken_languages", [])],
        "countries": [c["name"] for c in details.get("production_countries", [])],
        "director": [p["name"] for p in crew if p.get("job") == "Director"],
        "writer": [p["name"] for p in crew if p.get("job") in ("Writer", "Screenplay")],
        "cast": [p["name"] for p in cast[:15]],
        "plot": details.get("overview"),
        "tagline": details.get("tagline"),
        "poster_url": _pick_poster(details.get("images", {}), details.get("poster_path")),
        "backdrop_url": (f"{TMDB_IMG}{details['backdrop_path']}"
                          if details.get("backdrop_path") else None),
        "poster": _pick_poster(details.get("images", {}), details.get("poster_path")),
        "certificates": _certifications(details),
        "runtime": (f"{details.get('runtime')} min"
                     if media_type == "movie" and details.get("runtime") else None),
        "url": f"https://www.themoviedb.org/{media_type}/{details.get('id')}",
        "kind": "movie" if media_type == "movie" else "tv series",
        "seasons": details.get("number_of_seasons") if media_type == "tv" else None,
        "episodes": details.get("number_of_episodes") if media_type == "tv" else None,
        "images": images,
    }


async def fetch(query: str, bulk: bool = False,
                id: Optional[str] = None,
                file: Optional[str] = None):
    if not TMDB_API_KEY:
        return None
    async with aiohttp.ClientSession() as session:
        # Bulk search (for suggestion picker)
        if bulk:
            data = await _get(session, "search/multi", {
                "query": query, "language": "en-US", "include_adult": "false",
            })
            if not data:
                return []
            return [
                {
                    "title": r.get("title") or r.get("name"),
                    "year": int((r.get("release_date") or r.get("first_air_date") or "0000")[:4] or 0) or None,
                    "imdb_id": None,
                    "kind": "movie" if r.get("media_type") == "movie" else "tv series",
                }
                for r in data.get("results", [])[:10]
                if r.get("media_type") in ("movie", "tv")
            ]

        # By IMDb id
        if id:
            if str(id).startswith("tt"):
                find = await _get(session, f"find/{id}", {"external_source": "imdb_id"})
                if not find:
                    return None
                results = find.get("movie_results") or find.get("tv_results") or []
                if not results:
                    return None
                media_type = "movie" if find.get("movie_results") else "tv"
                d = await _details(session, media_type, results[0]["id"])
                return _normalize(d, media_type) if d else None
            else:
                # Numeric TMDB id — assume movie
                d = await _details(session, "movie", int(id))
                return _normalize(d, "movie") if d else None

        # Text search
        match = await _best_match(session, query, file)
        if not match:
            return None
        media_type, media_id = match
        d = await _details(session, media_type, media_id)
        return _normalize(d, media_type) if d else None
