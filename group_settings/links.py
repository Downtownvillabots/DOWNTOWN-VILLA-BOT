"""
Group Link Manager — Movie group + Series group links.
Used to redirect users when content mode blocks their search.
"""
import logging
import re
from typing import Optional

from group_settings.manager import config_manager

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)


def _valid_url(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    return bool(_URL_RE.match(url.strip()))


class GroupLinkManager:
    async def set_movie_link(self, chat_id: int, url: str) -> bool:
        if not _valid_url(url):
            return False
        return await config_manager.set_field(chat_id, "movie_group_link", url.strip())

    async def set_series_link(self, chat_id: int, url: str) -> bool:
        if not _valid_url(url):
            return False
        return await config_manager.set_field(chat_id, "series_group_link", url.strip())

    async def remove_movie_link(self, chat_id: int) -> bool:
        return await config_manager.set_field(chat_id, "movie_group_link", None)

    async def remove_series_link(self, chat_id: int) -> bool:
        return await config_manager.set_field(chat_id, "series_group_link", None)

    async def get_movie_link(self, chat_id: int) -> Optional[str]:
        cfg = await config_manager.get_config(chat_id)
        return cfg.get("movie_group_link")

    async def get_series_link(self, chat_id: int) -> Optional[str]:
        cfg = await config_manager.get_config(chat_id)
        return cfg.get("series_group_link")

    @staticmethod
    def is_valid_url(url: str) -> bool:
        return _valid_url(url)


link_manager = GroupLinkManager()
