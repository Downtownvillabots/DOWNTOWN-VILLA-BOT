"""
🔤 Spell check + suggestion engine.
Two-stage correction:
  1. Auto: fuzzy-match against metadata provider + verify with DB → re-search
  2. Manual: show title picker buttons → user picks → re-search
Never invents titles. Only suggests what exists in the metadata provider.
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

logger = logging.getLogger(__name__)


# ── Fuzzy matcher (rapidfuzz if available, difflib fallback) ──
try:
    from rapidfuzz import process as _rf_process, fuzz as _rf_fuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False
    from difflib import SequenceMatcher


def _score(a: str, b: str) -> int:
    """Return 0-100 similarity score."""
    if _HAS_RAPIDFUZZ:
        return int(_rf_fuzz.ratio(a.lower(), b.lower()))
    return int(SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100)


def _best_match(query: str, candidates: List[str]) -> Optional[Tuple[str, int]]:
    """Return (best_title, score) or None."""
    if not candidates:
        return None
    if _HAS_RAPIDFUZZ:
        result = _rf_process.extractOne(query, candidates)
        if not result:
            return None
        return result[0], int(result[1])
    # difflib fallback
    best_title = None
    best_score = -1
    for c in candidates:
        s = _score(query, c)
        if s > best_score:
            best_score = s
            best_title = c
    return (best_title, best_score) if best_title else None


# ═══════════════════════ STAGE 1 — AUTO CORRECT ═══════════════════════
async def ai_spell_check(wrong_name: str, is_series: bool = False) -> Optional[str]:
    """
    Try to auto-correct a misspelled query.
    Returns the corrected title ONLY if:
      - fuzzy match score >= SPELL_CHECK_THRESHOLD
      - AND the DB actually has files for that title
    Otherwise returns None.
    """
    if not wrong_name:
        return None

    # Fetch candidate titles from metadata provider
    try:
        suggestions = await metadata_provider.search(
            wrong_name, year=None, is_series=is_series,
        )
    except Exception as e:
        logger.warning(f"[SPELL] metadata search failed: {type(e).__name__}: {e}")
        return None

    if not suggestions:
        logger.info(f"[SPELL] no suggestions for {wrong_name!r}")
        return None

    titles = [s.get("title") for s in suggestions if s.get("title")]
    if not titles:
        return None

    # Try up to N candidates
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
            logger.info(f"[SPELL] best match {candidate!r} score {score} < {SPELL_CHECK_THRESHOLD}")
            break
        tried.append(candidate)

        # Verify DB has files
        norm = normalize(candidate)
        result = await engine.search_any(norm)
        if result.hits:
            logger.info(f"[SPELL] auto-corrected {wrong_name!r} → {candidate!r} (score={score})")
            return candidate
        else:
            logger.info(f"[SPELL] candidate {candidate!r} (score={score}) not in DB — trying next")

    return None


# ═══════════════════════ STAGE 2 — MANUAL PICKER DATA ═══════════════════════
async def get_suggestions(query: str, is_series: bool = False) -> List[Dict[str, Any]]:
    """
    Return a list of {title, year, metadata_id, poster} candidates from metadata.
    Used to render the "did you mean" picker buttons.
    Capped at MAX_LIST_ELM.
    """
    if not query:
        return []
    try:
        raw = await metadata_provider.search(query, year=None, is_series=is_series)
    except Exception as e:
        logger.warning(f"[SPELL] suggestions fetch failed: {e}")
        return []
    if not raw:
        return []
    # Ensure title uniqueness
    seen = set()
    out = []
    for s in raw:
        t = s.get("title")
        if not t or t in seen:
            continue
        seen.add(t)
        out.append({
            "title": t,
            "year": s.get("year"),
            "metadata_id": s.get("metadata_id"),
            "metadata_source": s.get("metadata_source"),
            "poster": s.get("poster"),
        })
        if len(out) >= MAX_LIST_ELM:
            break
    return out


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
    """Strip noise words from a user query for suggestion searches."""
    if not text:
        return ""
    q = _NOISE_RE.sub(" ", text)
    q = re.sub(r"\s+", " ", q).strip()
    return q or text.strip()
