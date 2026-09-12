"""
🔤 Spell check + suggestion engine.
Suggestions come from:
  1. IMDb (via services.imdb)  ← primary, no API key
  2. TMDB (via media_search.metadata)  ← fallback if IMDb fails

Two flows:
  - ai_spell_check: auto-correct if DB-verified (used only when SPELL_CHECK_REPLY=True)
  - get_suggestions: manual picker (always available)
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from core.config import (
    SPELL_CHECK_THRESHOLD, SPELL_CHECK_CANDIDATES, MAX_LIST_ELM,
)
from media_search.engine import engine
from media_search.metadata import metadata_provider
from media_search.normalizer import normalize
try:
    from services import imdb as imdb_service
    _HAS_IMDB_SERVICE = True
except Exception as e:
    import logging as _log
    _log.getLogger(__name__).warning(
        f"[SPELL] services.imdb unavailable: {type(e).__name__}: {e}"
    )
    imdb_service = None
    _HAS_IMDB_SERVICE = False

logger = logging.getLogger(__name__)


# ── Fuzzy matcher ──
try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False
    from difflib import SequenceMatcher


def _score(a: str, b: str) -> int:
    if _HAS_RAPIDFUZZ:
        return int(_rf_fuzz.ratio(a.lower(), b.lower()))
    return int(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)


def _best_match(query: str, candidates: List[str]) -> Optional[Tuple[str, int]]:
    if not candidates:
        return None
    if _HAS_RAPIDFUZZ:
        r = _rf_process.extractOne(query, candidates)
        return (r[0], int(r[1])) if r else None
    best_title, best_score = None, -1
    for c in candidates:
        s = _score(query, c)
        if s > best_score:
            best_score, best_title = s, c
    return (best_title, best_score) if best_title else None


# ═══════════════════════ SUGGESTION SOURCES ═══════════════════════
async def _get_imdb_suggestions(query: str) -> List[Dict[str, Any]]:
    """Primary source — IMDb via IMDBKit."""
    if not _HAS_IMDB_SERVICE or imdb_service is None:
        return []
    try:
        if not imdb_service.is_available():
            return []
    except Exception:
        return []
    if not briefs:
        return []
    out = []
    for b in briefs[:MAX_LIST_ELM]:
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
    return out


async def _get_tmdb_suggestions(query: str, is_series: bool = False) -> List[Dict[str, Any]]:
    """Fallback — TMDB via our metadata provider."""
    try:
        raw = await metadata_provider.search(query, year=None, is_series=is_series)
    except Exception as e:
        logger.warning(f"[SPELL] TMDB suggestions failed: {e}")
        return []
    if not raw:
        return []
    out = []
    for s in raw[:MAX_LIST_ELM]:
        title = s.get("title")
        if not title:
            continue
        out.append({
            "title": title,
            "year": s.get("year"),
            "metadata_id": s.get("metadata_id"),
            "metadata_source": s.get("metadata_source"),
            "poster": s.get("poster"),
        })
    return out


async def get_suggestions(query: str, is_series: bool = False) -> List[Dict[str, Any]]:
    """
    Return a list of {title, year, metadata_id, metadata_source, poster} candidates.
    IMDb first, TMDB fallback.
    """
    if not query:
        return []
    imdb_list = await _get_imdb_suggestions(query)
    if imdb_list:
        return imdb_list
    return await _get_tmdb_suggestions(query, is_series=is_series)


# ═══════════════════════ STAGE 1 — AUTO CORRECT ═══════════════════════
async def ai_spell_check(wrong_name: str, is_series: bool = False) -> Optional[str]:
    """
    DB-verified auto-correct.
    Returns corrected title only if:
      - fuzzy score >= SPELL_CHECK_THRESHOLD
      - AND engine finds files for that title.
    """
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
            logger.info(f"[SPELL] best {candidate!r} score {score} < {SPELL_CHECK_THRESHOLD}")
            break
        tried.append(candidate)
        # DB-verify
        norm = normalize(candidate)
        result = await engine.search_any(norm)
        if result.hits:
            logger.info(f"[SPELL] auto {wrong_name!r} → {candidate!r} (score={score})")
            return candidate
        logger.info(f"[SPELL] {candidate!r} not in DB — trying next")
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
