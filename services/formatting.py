"""Clean filename + size + duration formatting."""
import re
from typing import Optional


_JUNK_TOKENS = re.compile(
    r"\b(www|http|https|t\.me|telegram|\.com|\.net|\.org|\.to|\.cc|\.me|"
    r"\.tv|\.in|\.run|\.dog|\.xyz|\.site|\.app|\.link|"
    r"hdrip|webrip|web-dl|webdl|bluray|blu-ray|brrip|bdrip|"
    r"x264|x265|h264|h265|hevc|aac|ac3|ddp|dts|eac3|atmos|"
    r"esub|esubs|subs|sub|720p|1080p|480p|360p|2160p|4k|"
    r"10bit|8bit|hdr|multi|dual\s*audio)\b",
    re.IGNORECASE,
)


def clean_filename(name: Optional[str], max_len: int = 90) -> str:
    """
    Turn a messy filename into a human-readable title.
    - Strips extension
    - Removes @mentions, URLs, domains
    - Removes quality/codec tokens
    - Collapses separators
    """
    if not name:
        return ""
    n = str(name)

    # Remove extension
    n = re.sub(
        r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg|3gp|ogv|rmvb|srt|vtt|ass)$",
        "", n, flags=re.IGNORECASE,
    )

    # Remove @mentions and URLs
    n = re.sub(r"@[\w_]+", " ", n)
    n = re.sub(r"https?://\S+", " ", n)
    n = re.sub(r"www\.\S+", " ", n)

    # Remove domain-like patterns
    n = re.sub(
        r"\b[\w\-]+\.(com|net|org|to|cc|me|tv|in|run|dog|xyz|site|app|link)\b",
        " ", n, flags=re.IGNORECASE,
    )

    # Remove common junk tokens
    n = _JUNK_TOKENS.sub(" ", n)

    # Replace separators with spaces
    n = re.sub(r"[._\-+\[\]\(\)\{\}]+", " ", n)

    # Collapse spaces
    n = re.sub(r"\s+", " ", n).strip()

    # Trim surrounding punctuation
    n = n.strip(" -_.,:;'\"|/\\")

    # Title-case preservation: keep original but trim if too long
    if len(n) > max_len:
        n = n[: max_len - 1].rstrip() + "…"

    return n or "Unknown"


def get_size(size: Optional[int]) -> str:
    if not size:
        return "0 B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def get_time(seconds: int) -> str:
    if not seconds or seconds <= 0:
        return "0s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def human_size_short(size: Optional[int]) -> str:
    """Compact: '2.5 GB'"""
    if not size:
        return "0B"
    s = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    if s >= 100:
        return f"{int(s)}{units[i]}"
    return f"{s:.1f}{units[i]}"
