"""
Movie vs Series classifier.
Uses series metadata presence as the strongest signal.
Falls back to year + title heuristics for movies.
"""
from typing import Any, Dict, Optional
from indexing.parsers import extract_series, extract_year, normalize_title


def classify(text: str,
             series_info: Optional[Dict[str, Any]] = None,
             year: Optional[int] = None,
             title: Optional[str] = None) -> str:
    """
    Returns 'movie' | 'series' | 'unknown'.
    `series_info` wins if present.
    """
    if series_info is None:
        series_info = extract_series(text or "")
    if year is None:
        year = extract_year(text or "")
    if series_info:
        return "series"
    if title and normalize_title(title) and year:
        return "movie"
    # Title without year: try movie as fallback (best-effort)
    if title and normalize_title(title):
        return "movie"
    return "unknown"


def classify_record(record: Dict[str, Any]) -> str:
    return classify(
        text=record.get("normalized_name") or "",
        series_info=None if not record.get("season") else {
            "season": record["season"],
            "episode": record["episode"],
            "identifier": record.get("episode_identifier"),
        },
        year=record.get("year"),
        title=record.get("title"),
    )
