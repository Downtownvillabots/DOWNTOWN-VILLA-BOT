"""
Media database routing with operational threshold.
Reuses the media pool from db_registry — does not create new clients.
Threshold configurable via env: INDEXING_THRESHOLD_MB (default 400).
"""
import logging
import os
from typing import Optional, Tuple

from database import db_registry

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_MB = 400


class MediaRouter:
    def __init__(self, threshold_mb: Optional[int] = None):
        if threshold_mb is None:
            try:
                threshold_mb = int(os.getenv("INDEXING_THRESHOLD_MB", DEFAULT_THRESHOLD_MB))
            except (TypeError, ValueError):
                threshold_mb = DEFAULT_THRESHOLD_MB
        self.threshold_mb = max(50, threshold_mb)

    async def _used_mb(self, db) -> Optional[float]:
        try:
            s = await db.command("dbStats")
            used = (s.get("storageSize", 0) or 0) + (s.get("indexSize", 0) or 0)
            return used / (1024 * 1024)
        except Exception as e:
            logger.warning(f"dbStats failed during routing: {e}")
            return None

    async def pick_shard(self) -> Tuple[int, object]:
        """
        Return (shard_index, db) for next write.
        Raises RuntimeError if no shard is available.
        """
        entries = db_registry.media_entries()
        if not entries:
            raise RuntimeError("No media databases configured")
        last_error = None
        for entry in entries:
            used = await self._used_mb(entry.db)
            if used is None:
                last_error = f"Media DB {entry.index:02d} unreachable"
                continue
            if used < self.threshold_mb:
                return entry.index, entry.db
        if last_error:
            raise RuntimeError(last_error)
        raise RuntimeError(
            f"All media shards reached threshold ({self.threshold_mb} MB)"
        )

    async def status(self):
        """Return list of {index, label, used_mb, threshold_mb, pct, ok}."""
        out = []
        for entry in db_registry.media_entries():
            used = await self._used_mb(entry.db)
            if used is None:
                out.append({"index": entry.index, "label": entry.label,
                            "used_mb": None, "threshold_mb": self.threshold_mb,
                            "pct": 0.0, "ok": False})
                continue
            pct = min(100.0, (used / self.threshold_mb) * 100.0) if self.threshold_mb else 0.0
            out.append({"index": entry.index, "label": entry.label,
                        "used_mb": round(used, 2), "threshold_mb": self.threshold_mb,
                        "pct": round(pct, 1), "ok": used < self.threshold_mb})
        return out


media_router = MediaRouter()
