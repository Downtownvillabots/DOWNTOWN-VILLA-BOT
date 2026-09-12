"""
Caption renderer.
Supports per-group template override (groups.caption_template in DB).
Never raises — unknown variables render as empty strings.
"""
import logging
import re
from typing import Any, Dict, Optional

from database import db_registry
from media_search.config import (
    DEFAULT_FILE_CAPTION, DEFAULT_BATCH_CAPTION,
    SUPPORT_CHAT_URL, UPDATE_CHANNEL_URL,
)

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{(\w+)\}")


def _human_size(size: Optional[int]) -> str:
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


class CaptionRenderer:

    async def get_group_template(self, group_id: Optional[int]) -> Optional[str]:
        """Fetch per-group caption template if set."""
        if not group_id:
            return None
        db = db_registry.get_user_db()
        if db is None:
            return None
        try:
            doc = await db["groups"].find_one({"group_id": group_id})
            if doc:
                return doc.get("caption_template")
        except Exception:
            pass
        return None

    async def render_file(self, hit: Dict[str, Any], group_id: Optional[int] = None,
                          bot_username: str = "") -> str:
        template = await self.get_group_template(group_id) or DEFAULT_FILE_CAPTION
        return self._render(template, hit, bot_username)

    async def render_batch(self, item: Dict[str, Any], group_id: Optional[int] = None,
                           bot_username: str = "") -> str:
        template = await self.get_group_template(group_id) or DEFAULT_BATCH_CAPTION
        return self._render(template, item, bot_username)

    def _render(self, template: str, data: Dict[str, Any], bot_username: str) -> str:
        """Substitute {var} safely. Unknown vars → empty string."""
        ctx = {
            "title": data.get("title") or data.get("series_title") or "",
            "series_title": data.get("series_title") or data.get("title") or "",
            "year": data.get("year") or "",
            "quality": (data.get("quality") or "").upper(),
            "codec": (data.get("codec") or "").upper(),
            "audio": ", ".join(data.get("audio_languages") or []) or "—",
            "subtitle": ", ".join(data.get("subtitle_languages") or []) or "—",
            "language": ", ".join(data.get("audio_languages") or []) or "—",
            "size": _human_size(data.get("file_size")),
            "source": data.get("source") or "—",
            "release_group": data.get("release_group") or "—",
            "season": data.get("season") or "",
            "episode": data.get("episode") or "",
            "season_episode": (
                f"S{data['season']:02d}E{data['episode']:02d}"
                if data.get("season") and data.get("episode") else ""
            ),
            "bot_username": bot_username or "",
            "bot_link": f"https://t.me/{bot_username}" if bot_username else "",
            "group_link": SUPPORT_CHAT_URL or "",
            "channel_link": UPDATE_CHANNEL_URL or "",
        }

        def _sub(m):
            key = m.group(1)
            return str(ctx.get(key, ""))

        try:
            return _VAR_RE.sub(_sub, template)
        except Exception as e:
            logger.warning(f"[CAPTION] render failed: {e}")
            return template


caption_renderer = CaptionRenderer()
