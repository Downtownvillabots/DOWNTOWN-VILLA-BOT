"""
Preferred release ranking.
Picks the best release per (title, language, quality) group.
Never removes other releases — only annotates which is preferred.
"""
import logging
from typing import List, Optional

from media_search.config import (
    PREFERRED_QUALITY, PREFERRED_CODEC, PREFERRED_AUDIO, PREFERRED_SUBTITLE,
)
from media_search.models import FileHit

logger = logging.getLogger(__name__)

_QUALITY_ORDER = {
    "2160P": 100, "1440P": 90, "1080P": 80, "1080I": 70,
    "720P": 60, "576P": 50, "480P": 40, "360P": 30,
}
_CODEC_ORDER = {"HEVC": 30, "H264": 20, "AV1": 40, "VP9": 25, "MPEG4": 10}


class ReleaseRanker:

    @staticmethod
    def score(hit: FileHit) -> float:
        """Higher is better."""
        score = 0.0

        # Quality
        q = (hit.quality or "").upper()
        score += _QUALITY_ORDER.get(q, 10)
        if q == PREFERRED_QUALITY.upper():
            score += 20

        # Codec
        c = (hit.codec or "").upper()
        score += _CODEC_ORDER.get(c, 5)
        if c == PREFERRED_CODEC.upper():
            score += 10

        # Audio
        if PREFERRED_AUDIO in (hit.audio_languages or []):
            score += 8

        # Subtitle
        if PREFERRED_SUBTITLE in (hit.subtitle_languages or []):
            score += 5
        if hit.has_subtitle:
            score += 2

        # Source preference (BluRay > WEB-DL > WEBRip > others)
        src = (hit.source or "").upper()
        if src in ("BLURAY", "BRRIP", "BDRIP"):
            score += 6
        elif src in ("WEB-DL", "WEB"):
            score += 5
        elif src in ("WEBRIP", "HDTV"):
            score += 3

        return score

    @staticmethod
    def rank(hits: List[FileHit]) -> List[FileHit]:
        """Sort descending by score."""
        return sorted(hits, key=ReleaseRanker.score, reverse=True)

    @staticmethod
    def best_for_episode(episode_hits: List[FileHit]) -> Optional[FileHit]:
        """Pick the single best release for one episode."""
        if not episode_hits:
            return None
        return max(episode_hits, key=ReleaseRanker.score)

    @staticmethod
    def best_per_episode(all_hits: List[FileHit]) -> List[FileHit]:
        """
        Given many series hits, return the best release for each unique episode.
        Groups by (season, episode).
        """
        groups = {}
        for h in all_hits:
            if h.season is None or h.episode is None:
                continue
            key = (h.season, h.episode)
            groups.setdefault(key, []).append(h)

        out: List[FileHit] = []
        for key in sorted(groups.keys()):
            best = ReleaseRanker.best_for_episode(groups[key])
            if best:
                out.append(best)
        return out

    @staticmethod
    def group_by_quality(hits: List[FileHit]) -> dict:
        """Group hits by normalized quality for UI display."""
        out: dict = {}
        for h in hits:
            q = (h.quality or "UNKNOWN").upper()
            out.setdefault(q, []).append(h)
        # Sort each group
        for q in out:
            out[q] = ReleaseRanker.rank(out[q])
        return out


ranker = ReleaseRanker()
