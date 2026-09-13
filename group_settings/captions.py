"""
Caption Manager.
Per-group caption templates with variable substitution.
Falls back to global default if group has no custom caption.
Never crashes on missing fields.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from group_settings.manager import config_manager

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{(\w+)\}")

# Variables supported in templates
AVAILABLE_VARIABLES: List[str] = [
    "title", "year", "quality", "codec", "audio", "subtitle",
    "language", "size", "season", "episode", "series_title",
    "source", "release_group", "group_link", "channel_link", "bot_link",
]


def _human_size(size: Optional[int]) -> str:
    if not size:
        return "—"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


class CaptionManager:
    async def set_caption(self, chat_id: int, template: str) -> bool:
        if not template or not template.strip():
            return False
        return await config_manager.set_field(chat_id, "custom_caption", template.strip())

    async def remove_caption(self, chat_id: int) -> bool:
        return await config_manager.set_field(chat_id, "custom_caption", None)

    async def get_caption(self, chat_id: int) -> Optional[str]:
        cfg = await config_manager.get_config(chat_id)
        return cfg.get("custom_caption")

    async def render(self, chat_id: int, data: Dict[str, Any],
                     bot_username: str = "") -> str:
        """Substitute variables in the group's caption (or global default)."""
        template = await self.get_caption(chat_id)
        if not template:
            from media_search.config import DEFAULT_FILE_CAPTION
            template = DEFAULT_FILE_CAPTION
        return self._substitute(template, data, bot_username)

    def render_with_template(self, template: str, data: Dict[str, Any],
                             bot_username: str = "") -> str:
        return self._substitute(template, data, bot_username)

    def _substitute(self, template: str, data: Dict[str, Any],
                    bot_username: str) -> str:
        ctx: Dict[str, str] = {
            "title": str(data.get("title") or data.get("series_title") or ""),
            "series_title": str(data.get("series_title") or data.get("title") or ""),
            "year": str(data.get("year") or ""),
            "quality": str(data.get("quality") or "").upper(),
            "codec": str(data.get("codec") or "").upper(),
            "audio": ", ".join(data.get("audio_languages") or []) or "—",
            "subtitle": ", ".join(data.get("subtitle_languages") or []) or "—",
            "language": ", ".join(data.get("audio_languages") or []) or "—",
            "size": _human_size(data.get("file_size")),
            "season": str(data.get("season") or ""),
            "episode": str(data.get("episode") or ""),
            "source": str(data.get("source") or "—"),
            "release_group": str(data.get("release_group") or "—"),
            "bot_username": bot_username or "",
            "bot_link": f"https://t.me/{bot_username}" if bot_username else "",
            "group_link": str(data.get("group_link") or ""),
            "channel_link": str(data.get("channel_link") or ""),
        }
        # Ensure no None leaks
        def _sub(m):
            k = m.group(1)
            v = ctx.get(k, "")
            return v if v not in (None, "None", "null") else ""
        try:
            return _VAR_RE.sub(_sub, template)
        except Exception as e:
            logger.warning(f"[CAPTION] render failed: {e}")
            return template

    async def preview(self, chat_id: int) -> str:
        """Render with sample data."""
        sample = {
            "title": "KGF: Chapter 1",
            "year": 2018,
            "quality": "1080p",
            "codec": "HEVC",
            "audio_languages": ["Malayalam", "Hindi"],
            "subtitle_languages": ["English"],
            "file_size": 2_576_980_378,   # ~2.4 GB
            "season": None,
            "episode": None,
            "source": "WEB-DL",
        }
        cfg = await config_manager.get_config(chat_id)
        # Try group links
        sample["group_link"] = cfg.get("movie_group_link") or "https://t.me/example"
        sample["channel_link"] = cfg.get("series_group_link") or "https://t.me/example"
        return await self.render(chat_id, sample, bot_username="examplebot")


caption_manager = CaptionManager()
