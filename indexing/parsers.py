"""
Metadata parsers. Metadata-first, no file download.
Every parser is a pure function: text in → structured data out.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

from indexing.aliases import (
    LANGUAGE_ALIASES, SUBTITLE_KEYWORDS, SUBTITLE_PHRASES,
    QUALITY_ALIASES, QUALITY_PRIORITY, CODEC_ALIASES, SOURCE_ALIASES,
    MISC_NOISE, PREFIX_PATTERNS, AT_MENTION,
)

# ─────────── Separator / normalisation ───────────
_SEP_RE = re.compile(r"[._\-\[\]\(\)]+")
_MULTISPACE = re.compile(r"\s+")
_BRACKETS = re.compile(r"[\[\]\(\)\{\}]")

# ─────────── Series patterns ───────────
SERIES_PATTERNS = [
    # S01E01, S1.E1, S01.E01, S01 E01, S01-E01
    re.compile(r"\bS(\d{1,2})[\s._\-]*E(\d{1,3})\b", re.IGNORECASE),
    # 1x01, 01x01
    re.compile(r"\b(\d{1,2})x(\d{1,3})\b", re.IGNORECASE),
    # Season 1 Episode 5 / S01 EP05
    re.compile(r"\bS(?:eason)?\s*(\d{1,2})\s*(?:E|EP|Episode)\s*(\d{1,3})\b", re.IGNORECASE),
]
# Looser season-only patterns (paired with an episode pattern)
SEASON_ONLY = re.compile(r"\bS(?:eason)?\s*(\d{1,2})\b", re.IGNORECASE)
EPISODE_ONLY = re.compile(r"\b(?:E|EP|Episode)\s*(\d{1,3})\b", re.IGNORECASE)

# ─────────── Year ───────────
YEAR_RE = re.compile(r"\b(19[3-9]\d|20[0-4]\d|2050)\b")


# ═══════════════════════════════════════════════════════════════
# CLEANING
# ═══════════════════════════════════════════════════════════════
def strip_prefixes(text: str) -> str:
    """Remove leading watermark prefixes like @Channel_, [Group], (Tag)."""
    prev = None
    while prev != text:
        prev = text
        for pat in PREFIX_PATTERNS:
            text = pat.sub("", text, count=1)
    return text.strip()


def strip_at_mentions(text: str) -> str:
    """Remove any remaining @username mentions."""
    return AT_MENTION.sub(" ", text)


def clean_text(text: Optional[str]) -> str:
    """Normalise separators, strip watermarks, collapse spaces."""
    if not text:
        return ""
    t = text.strip()
    t = strip_prefixes(t)
    t = strip_at_mentions(t)
    t = _SEP_RE.sub(" ", t)
    t = _BRACKETS.sub(" ", t)
    t = _MULTISPACE.sub(" ", t).strip()
    return t


def split_tokens(text: str) -> List[str]:
    return [tok for tok in text.split(" ") if tok]


# ═══════════════════════════════════════════════════════════════
# EXTRACTORS
# ═══════════════════════════════════════════════════════════════
def extract_series(text: str) -> Optional[Dict[str, Any]]:
    """Return {'season': int, 'episode': int, 'identifier': str} or None."""
    for pat in SERIES_PATTERNS:
        m = pat.search(text)
        if m:
            s, e = int(m.group(1)), int(m.group(2))
            if 0 < s < 100 and 0 < e < 10000:
                return {
                    "season": s,
                    "episode": e,
                    "identifier": f"S{s:02d}E{e:02d}",
                }
    # Fall back: season-only + episode-only in same text
    sm = SEASON_ONLY.search(text)
    em = EPISODE_ONLY.search(text)
    if sm and em:
        s, e = int(sm.group(1)), int(em.group(1))
        if 0 < s < 100 and 0 < e < 10000:
            return {
                "season": s,
                "episode": e,
                "identifier": f"S{s:02d}E{e:02d}",
            }
    return None


def extract_year(text: str) -> Optional[int]:
    """Find the last valid 4-digit year in the text."""
    candidates = [int(m.group(1)) for m in YEAR_RE.finditer(text)]
    if not candidates:
        return None
    # Prefer 1950–current+1
    for y in reversed(candidates):
        if 1950 <= y <= 2050:
            return y
    return None


def extract_quality(tokens: List[str]) -> Optional[str]:
    """Normalise quality token (2160p / 1080p / 720p ...)."""
    found: List[str] = []
    for tok in tokens:
        low = tok.lower().rstrip("p") if tok.lower().endswith("p") else tok.lower()
        # Direct map
        if low in QUALITY_ALIASES:
            found.append(QUALITY_ALIASES[low])
        elif tok.lower() in QUALITY_ALIASES:
            found.append(QUALITY_ALIASES[tok.lower()])
    if not found:
        return None
    for q in QUALITY_PRIORITY:
        if q in found:
            return q
    return found[0]


def extract_codec(tokens: List[str]) -> Optional[str]:
    for tok in tokens:
        low = tok.lower()
        if low in CODEC_ALIASES:
            return CODEC_ALIASES[low]
    return None


def extract_source(tokens: List[str]) -> Optional[str]:
    for tok in tokens:
        low = tok.lower()
        if low in SOURCE_ALIASES:
            return SOURCE_ALIASES[low]
    return None


def extract_audio_languages(tokens: List[str]) -> List[str]:
    langs: List[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in LANGUAGE_ALIASES:
            canonical = LANGUAGE_ALIASES[low]
            if canonical not in langs:
                langs.append(canonical)
    return langs


def extract_subtitle(text: str, tokens: List[str]) -> Tuple[bool, List[str], Optional[str]]:
    """
    Returns (has_subtitle, subtitle_languages, subtitle_raw).
    Uses contextual parsing for 'SUB' tokens + phrase patterns like 'ENG SUB'.
    """
    raw_parts: List[str] = []
    sub_langs: List[str] = []

    # Phrase: 'eng sub', 'hindi subtitle', etc.
    for m in SUBTITLE_PHRASES.finditer(text):
        raw_parts.append(m.group(0))
        lang_alias = m.group(1).lower()
        if lang_alias in LANGUAGE_ALIASES:
            canon = LANGUAGE_ALIASES[lang_alias]
            if canon not in sub_langs:
                sub_langs.append(canon)

    # Bare SUB / SUBS tokens
    has_bare_sub = False
    for tok in tokens:
        if tok.lower() in SUBTITLE_KEYWORDS:
            has_bare_sub = True
            raw_parts.append(tok)

    has_sub = has_bare_sub or bool(sub_langs)
    raw = " ".join(raw_parts) if raw_parts else None
    return has_sub, sub_langs, raw


# ═══════════════════════════════════════════════════════════════
# TITLE EXTRACTION
# ═══════════════════════════════════════════════════════════════
def _is_metadata_token(tok: str) -> bool:
    """Return True if token is NOT part of a title."""
    low = tok.lower().strip(".,:;")
    if not low:
        return True
    if low in QUALITY_ALIASES: return True
    if low in CODEC_ALIASES: return True
    if low in SOURCE_ALIASES: return True
    if low in LANGUAGE_ALIASES: return True
    if low in SUBTITLE_KEYWORDS: return True
    if low in MISC_NOISE: return True
    if YEAR_RE.fullmatch(low): return True
    # Series markers
    if re.fullmatch(r"s\d{1,2}(?:e\d{1,3})?", low): return True
    if re.fullmatch(r"e\d{1,3}", low): return True
    if re.fullmatch(r"\d{1,2}x\d{1,3}", low): return True
    if re.fullmatch(r"(season|episode|ep|s|e)\d{1,3}", low): return True
    # Purely numeric tokens (size, part numbers like "part1")
    if re.fullmatch(r"\d+", low): return True
    # Resolutions like "1080", "720"
    if re.fullmatch(r"2160|1440|1080|720|576|480|360", low): return True
    # Extensions
    if low in {"mkv", "mp4", "avi", "mov", "wmv", "flv", "webm", "m4v",
               "ts", "m2ts", "mpg", "mpeg", "3gp", "ogv", "rmvb"}:
        return True
    return False


def extract_title(tokens: List[str], series: Optional[Dict[str, Any]] = None) -> str:
    """Remove all metadata tokens, join what remains as the title."""
    kept: List[str] = []
    for tok in tokens:
        if _is_metadata_token(tok):
            continue
        kept.append(tok)
    title = " ".join(kept).strip()
    # Collapse repeated spaces / leftover punctuation
    title = _MULTISPACE.sub(" ", title).strip(" -_.:,;")
    # Title-case for readability (preserve all-caps words of length > 2? — keep simple)
    if title:
        title = " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize()
                          for w in title.split())
    return title


def normalize_title(title: str) -> str:
    """Lowercase, strip non-alphanumeric except spaces, collapse spaces."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    t = _MULTISPACE.sub(" ", t).strip()
    return t


# ═══════════════════════════════════════════════════════════════
# MASTER PARSER
# ═══════════════════════════════════════════════════════════════
def extract_metadata(filename: Optional[str],
                     caption: Optional[str] = None) -> Dict[str, Any]:
    """
    Combine filename + caption, extract all possible metadata.
    Never invents fields — unknown = None / [] / False.
    """
    raw_name = (filename or "").strip()
    raw_cap = (caption or "").strip()

    # Remove file extension before parsing
    name_no_ext = re.sub(
        r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg|3gp|ogv|rmvb|srt|vtt|ass)$",
        "", raw_name, flags=re.IGNORECASE,
    )

    combined_raw = f"{name_no_ext} {raw_cap}".strip()
    cleaned = clean_text(combined_raw)
    tokens = split_tokens(cleaned)

    series = extract_series(cleaned)
    year = extract_year(cleaned)
    quality = extract_quality(tokens)
    codec = extract_codec(tokens)
    source = extract_source(tokens)
    audio = extract_audio_languages(tokens)
    has_sub, sub_langs, sub_raw = extract_subtitle(cleaned, tokens)
    title = extract_title(tokens, series)

    return {
        "original_name": raw_name or None,
        "normalized_name": cleaned or None,
        "caption": raw_cap or None,
        "clean_caption": cleaned or None,

        "title": title or None,
        "normalized_title": normalize_title(title) if title else None,
        "year": year,

        "type": "series" if series else ("movie" if title and year else "unknown"),

        "quality": quality,
        "codec": codec,
        "source": source,

        "audio_languages": audio,
        "has_subtitle": has_sub,
        "subtitle_languages": sub_langs,
        "subtitle_raw": sub_raw,

        "series_title": title if series else None,
        "normalized_series_title": normalize_title(title) if series else None,
        "season": series["season"] if series else None,
        "episode": series["episode"] if series else None,
        "episode_identifier": series["identifier"] if series else None,
    }
