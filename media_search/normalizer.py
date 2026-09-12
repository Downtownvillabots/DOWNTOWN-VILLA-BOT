"""
Query normalization for user search input.
KGF / K.G.F / K-G-F / K G F → kgf
Preserves meaningful punctuation in known patterns.
"""
import re
from typing import Optional, Tuple

# Common stop words to strip from user queries
STOP_WORDS = {
    "movie", "movies", "film", "films",
    "download", "watch", "online", "free",
    "hd", "full", "the", "and",
}

# Series markers — if query contains these, mark as series
SERIES_MARKERS = re.compile(
    r"\b(s\d{1,2}(?:e\d{1,3})?|season\s*\d+|episode\s*\d+|ep\s*\d+|\d+x\d+)\b",
    re.IGNORECASE,
)

# Year pattern
YEAR_RE = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")

# Quality tokens to strip from query
_QUALITY_TOKENS = re.compile(
    r"\b(2160p|4k|uhd|1440p|1080p|1080i|720p|576p|480p|360p|fhd|hd|sd)\b",
    re.IGNORECASE,
)
_CODEC_TOKENS = re.compile(
    r"\b(hevc|h\.?265|x265|h\.?264|x264|avc|av1|vp9|web-?dl|webrip|bluray|blu-?ray|"
    r"brrip|bdrip|hdrip|dvdrip|hdtv|hdcam|cam|pre-?dvd)\b",
    re.IGNORECASE,
)
_LANG_TOKENS = re.compile(
    r"\b(eng|en|english|hin|hi|hindi|mal|ml|malayalam|tam|ta|tamil|"
    r"tel|te|telugu|kan|kn|kannada|multi)\b",
    re.IGNORECASE,
)


def _collapse_separators(text: str) -> str:
    """K.G.F → KGF, K-G-F → KGF, K G F → KGF"""
    # Replace dots, dashes, underscores, slashes, commas with space
    text = re.sub(r"[.\-_/,;:\\]+", " ", text)
    # Collapse repeated spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _squeeze_single_letters(text: str) -> str:
    """K G F → KGF. Only if 3+ consecutive single-letter words."""
    tokens = text.split()
    if len(tokens) < 2:
        return text
    # Count consecutive single-char tokens
    out = []
    buf = []
    for tok in tokens:
        if len(tok) == 1 and tok.isalpha():
            buf.append(tok)
        else:
            if len(buf) >= 2:
                out.append("".join(buf))
            else:
                out.extend(buf)
            buf = []
            out.append(tok)
    if len(buf) >= 2:
        out.append("".join(buf))
    else:
        out.extend(buf)
    return " ".join(out)


def normalize(text: Optional[str]) -> str:
    """
    Normalize user query for search matching.
    Returns lowercase, punctuation-collapsed, whitespace-collapsed string.
    """
    if not text:
        return ""
    t = text.strip().lower()
    t = _collapse_separators(t)
    t = _squeeze_single_letters(t)
    # Remove standalone punctuation that's not useful
    t = re.sub(r"[^\w\s]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_year(text: str) -> Optional[int]:
    if not text:
        return None
    matches = [int(m.group(1)) for m in YEAR_RE.finditer(text)]
    return matches[-1] if matches else None


def is_series_query(text: str) -> bool:
    return bool(SERIES_MARKERS.search(text or ""))


def strip_metadata_tokens(text: str) -> str:
    """Remove quality/codec/language/year tokens before matching."""
    if not text:
        return ""
    t = _QUALITY_TOKENS.sub(" ", text)
    t = _CODEC_TOKENS.sub(" ", t)
    t = _LANG_TOKENS.sub(" ", t)
    t = YEAR_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_query(raw: str) -> Tuple[str, Optional[int], bool]:
    """
    Returns (normalized_title, year, is_series).
    Strips metadata tokens before matching so "KGF 2018 1080p" → "kgf", 2018, False.
    """
    year = extract_year(raw)
    is_series = is_series_query(raw)
    stripped = strip_metadata_tokens(raw)
    if not stripped:
        stripped = raw
    normalized = normalize(stripped)
    # Remove stop words
    words = [w for w in normalized.split() if w not in STOP_WORDS]
    normalized = " ".join(words).strip()
    return normalized, year, is_series
