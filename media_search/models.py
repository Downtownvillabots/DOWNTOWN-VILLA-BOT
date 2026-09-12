"""
Core dataclasses for the search system.
Plain Python — no external deps.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════ USER-FACING ═══════════════════════
@dataclass
class TitleCandidate:
    """A movie or series that matched the user query."""
    type: str                        # "movie" | "series"
    title: str
    normalized_title: str
    year: Optional[int] = None
    poster: Optional[str] = None
    rating: Optional[float] = None
    genres: List[str] = field(default_factory=list)
    overview: Optional[str] = None
    languages: List[str] = field(default_factory=list)   # canonical
    qualities: List[str] = field(default_factory=list)   # canonical
    file_count: int = 0
    metadata_id: Optional[str] = None                    # tmdb/imdb id
    metadata_source: Optional[str] = None
    confidence: float = 1.0


@dataclass
class FileHit:
    """One Telegram file that matches a search."""
    file_id: str
    file_unique_id: Optional[str]
    file_name: Optional[str]
    file_size: Optional[int]
    title: str
    normalized_title: str
    year: Optional[int] = None
    type: str = "movie"
    quality: Optional[str] = None
    codec: Optional[str] = None
    source: Optional[str] = None
    audio_languages: List[str] = field(default_factory=list)
    subtitle_languages: List[str] = field(default_factory=list)
    has_subtitle: bool = False
    # series
    series_title: Optional[str] = None
    normalized_series_title: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_identifier: Optional[str] = None
    # meta
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    shard_index: int = 0
    caption: Optional[str] = None

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any], shard_index: int = 0) -> "FileHit":
        return cls(
            file_id=doc.get("file_id", ""),
            file_unique_id=doc.get("file_unique_id"),
            file_name=doc.get("file_name"),
            file_size=doc.get("file_size"),
            title=doc.get("title") or "",
            normalized_title=doc.get("normalized_title") or "",
            year=doc.get("year"),
            type=doc.get("type") or "movie",
            quality=doc.get("quality"),
            codec=doc.get("codec"),
            source=doc.get("source"),
            audio_languages=list(doc.get("audio_languages") or []),
            subtitle_languages=list(doc.get("subtitle_languages") or []),
            has_subtitle=bool(doc.get("has_subtitle")),
            series_title=doc.get("series_title"),
            normalized_series_title=doc.get("normalized_series_title"),
            season=doc.get("season"),
            episode=doc.get("episode"),
            episode_identifier=doc.get("episode_identifier"),
            channel_id=doc.get("channel_id"),
            message_id=doc.get("message_id"),
            shard_index=shard_index,
            caption=doc.get("caption"),
        )


@dataclass
class SearchResult:
    """Result of searching all shards."""
    hits: List[FileHit] = field(default_factory=list)
    complete: bool = True            # False if any shard failed
    failed_shards: List[int] = field(default_factory=list)
    elapsed_ms: float = 0.0
    from_cache: bool = False


# ═══════════════════════ SESSION ═══════════════════════
@dataclass
class SearchSession:
    session_id: str
    user_id: int
    chat_id: int
    query: str
    normalized_query: str
    mode: str = "movie"              # "movie" | "series"

    selected_title: Optional[str] = None
    selected_normalized_title: Optional[str] = None
    selected_year: Optional[int] = None
    selected_language: Optional[str] = None
    selected_quality: Optional[str] = None
    selected_season: Optional[int] = None
    selected_episode: Optional[int] = None

    candidates: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float = 0.0

    def to_mongo(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "chat_id": self.chat_id,
            "query": self.query,
            "normalized_query": self.normalized_query,
            "mode": self.mode,
            "selected_title": self.selected_title,
            "selected_normalized_title": self.selected_normalized_title,
            "selected_year": self.selected_year,
            "selected_language": self.selected_language,
            "selected_quality": self.selected_quality,
            "selected_season": self.selected_season,
            "selected_episode": self.selected_episode,
            "candidates": self.candidates,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_mongo(cls, doc: Dict[str, Any]) -> "SearchSession":
        return cls(
            session_id=doc["session_id"],
            user_id=doc["user_id"],
            chat_id=doc["chat_id"],
            query=doc.get("query", ""),
            normalized_query=doc.get("normalized_query", ""),
            mode=doc.get("mode", "movie"),
            selected_title=doc.get("selected_title"),
            selected_normalized_title=doc.get("selected_normalized_title"),
            selected_year=doc.get("selected_year"),
            selected_language=doc.get("selected_language"),
            selected_quality=doc.get("selected_quality"),
            selected_season=doc.get("selected_season"),
            selected_episode=doc.get("selected_episode"),
            candidates=list(doc.get("candidates") or []),
            created_at=doc.get("created_at", 0.0),
            updated_at=doc.get("updated_at", 0.0),
            expires_at=doc.get("expires_at", 0.0),
        )
