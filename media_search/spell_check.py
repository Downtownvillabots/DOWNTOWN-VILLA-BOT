"""
🔤 DOWNTOWN VILLA — Spell check + suggestions.
Uses IMDb (via services.imdb) as primary source.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.config import (
    SPELL_CHECK_THRESHOLD, SPELL_CHECK_CANDIDATES, MAX_LIST_ELM,
)
from media_search.engine import engine
from media_search.metadata import metadata_provider
from media_search.normalizer import normalize
from services import imdb as imdb_service

logger = logging.getLogger(__name__)

try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
    _HAS_RF = True
except ImportError:
    _HAS_RF = False
    from difflib import SequenceMatcher


def _score(a: str, b: str) -> int:
    if _HAS_RF:
        return int(_rf_fuzz.ratio(a.lower(), b.lower()))
    return int(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)


def _best_match(query: str, candidates: List[str]) -> Optional[Tuple[str, int]]:
    if not candidates:
        return None
    if _HAS_RF:
        r = _rf_process.extractOne(query, candidates)
        return (r[0], int(r[1])) if r else None
    best_t, best_s = None, -1
    for c in candidates:
        s = _score(query, c)
        if s > best_s:
            best_s, best_t = s, c
    return (best_t, best_s) if best_t else None


# ═══════════════════════ SUGGESTIONS ═══════════════════════
async def _imdb_suggestions(query: str) -> List[Dict[str, Any]]:
    """Fetch brief titles from IMDb."""
    if not imdb_service.is_available():
        logger.info("[SPELL] IMDb not available")
        return []
    try:
        briefs = await imdb_service.get_poster(query, bulk=True)
    except Exception as e:
        logger.warning(f"[SPELL] IMDb get_poster failed: {type(e).__name__}: {e}")
        return []

    if not briefs or not isinstance(briefs, list):
        logger.info(f"[SPELL] IMDb returned no briefs for {query!r}")
        return []

    out: List[Dict[str, Any]] = []
    for b in briefs:
        if not isinstance(b, dict):
            continue
        title = b.get("title")
        if not title:
            continue
        out.append({
            "title": title,
            "year": b.get("year"),
            "metadata_id": b.get("imdb_id"),
            "metadata_source": "imdb",
            "poster": None,
        })
        if len(out) >= (MAX_LIST_ELM or 10):
            break
    logger.info(f"[SPELL] IMDb returned {len(out)} suggestions for {query!r}")
    return out


async def _tmdb_suggestions(query: str, is_series: bool = False) -> List[Dict[str, Any]]:
    try:
        raw = await metadata_provider.search(query, year=None, is_series=is_series)
    except Exception as e:
        logger.warning(f"[SPELL] TMDB failed: {type(e).__name__}: {e}")
        return []
    if not raw:
        return []
    out = []
    for s in raw:
        t = s.get("title")
        if not t:
            continue
        out.append({
            "title": t,
            "year": s.get("year"),
            "metadata_id": s.get("metadata_id"),
            "metadata_source": s.get("metadata_source"),
            "poster": s.get("poster"),
        })
        if len(out) >= (MAX_LIST_ELM or 10):
            break
    return out


async def get_suggestions(query: str, is_series: bool = False) -> List[Dict[str, Any]]:
    """IMDb first, TMDB fallback."""
    if not query:
        return []
    imdb_list = await _imdb_suggestions(query)
    if imdb_list:
        return imdb_list
    return await _tmdb_suggestions(query, is_series=is_series)


# ═══════════════════════ AUTO-CORRECT (DB-verified) ═══════════════════════
async def ai_spell_check(wrong_name: str, is_series: bool = False) -> Optional[str]:
    """Return corrected title only if score >= threshold AND title exists in DB."""
    if not wrong_name:
        return None

    suggestions = await get_suggestions(wrong_name, is_series=is_series)
    titles = [s.get("title") for s in suggestions if s.get("title")]
    if not titles:
        return None

    tried: List[str] = []
    for _ in range(SPELL_CHECK_CANDIDATES):
        remaining = [t for t in titles if t not in tried]
        if not remaining:
            break
        match = _best_match(wrong_name, remaining)
        if not match:
            break
        candidate, score = match
        if score < SPELL_CHECK_THRESHOLD:
            break
        tried.append(candidate)
        norm = normalize(candidate)
        result = await engine.search_any(norm)
        if result.hits:
            logger.info(f"[SPELL] corrected {wrong_name!r} → {candidate!r} (score={score})")
            return candidate
    return None


# ═══════════════════════ QUERY CLEANER ═══════════════════════
_NOISE_RE = re.compile(
    r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|"
    r"((send|snd|giv(e)?|gib)(\sme)?)|"
    r"movie(s)?|new|latest|br((o|u)h?)*|"
    r"^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|"
    r"file|that|find|und(o)*|"
    r"kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|"
    r"aya(k)*(um(o)*)?|full\smovie|any(one)|"
    r"with\ssubtitle(s)?)\b",
    re.IGNORECASE,
)


def clean_query(text: str) -> str:
    if not text:
        return ""
    q = _NOISE_RE.sub(" ", text)
    q = re.sub(r"\s+", " ", q).strip()
    return q or text.strip()
