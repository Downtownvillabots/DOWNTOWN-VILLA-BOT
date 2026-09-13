"""
Permission Manager.
Validates: bot owner, group admin, group owner.
Caches `get_chat_member` results briefly to reduce Telegram API calls.
"""
import logging
import time
from typing import Dict, Optional, Tuple

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import ChatAdminRequired, UserNotParticipant, ChannelPrivate

from core.config import ADMINS

logger = logging.getLogger(__name__)

_MEMBER_CACHE: Dict[Tuple[int, int], Tuple[str, float]] = {}
_MEMBER_TTL = 60  # seconds


class PermissionManager:
    # ────────── BOT OWNER ──────────
    @staticmethod
    def is_bot_owner(user_id: int) -> bool:
        try:
            return int(user_id) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
        except Exception:
            return False

    # ────────── GROUP ADMIN / OWNER ──────────
    async def _get_status(self, client: Client, chat_id: int, user_id: int) -> Optional[str]:
        key = (chat_id, user_id)
        cached = _MEMBER_CACHE.get(key)
        if cached and time.time() - cached[1] < _MEMBER_TTL:
            return cached[0]
        try:
            member = await client.get_chat_member(chat_id, user_id)
            status = getattr(member, "status", None)
            if hasattr(status, "name"):
                status = status.name.lower()
            else:
                status = str(status).lower()
            _MEMBER_CACHE[key] = (status, time.time())
            return status
        except (ChatAdminRequired, ChannelPrivate):
            return None
        except UserNotParticipant:
            return "not_member"
        except Exception as e:
            logger.warning(f"[PERM] get_chat_member failed for {chat_id}/{user_id}: {e}")
            return None

    async def is_group_admin(self, client: Client, chat_id: int, user_id: int) -> bool:
        status = await self._get_status(client, chat_id, user_id)
        return status in ("administrator", "creator", "owner")

    async def is_group_owner(self, client: Client, chat_id: int, user_id: int) -> bool:
        status = await self._get_status(client, chat_id, user_id)
        return status in ("creator", "owner")

    async def can_manage(self, client: Client, chat_id: int, user_id: int) -> bool:
        """Bot owner OR group admin."""
        if self.is_bot_owner(user_id):
            return True
        return await self.is_group_admin(client, chat_id, user_id)

    async def bot_is_admin(self, client: Client, chat_id: int) -> bool:
        try:
            me = await client.get_me()
            return await self.is_group_admin(client, chat_id, me.id)
        except Exception:
            return False

    def invalidate_cache(self, chat_id: int, user_id: Optional[int] = None) -> None:
        if user_id is None:
            for k in [k for k in _MEMBER_CACHE if k[0] == chat_id]:
                _MEMBER_CACHE.pop(k, None)
        else:
            _MEMBER_CACHE.pop((chat_id, user_id), None)

    def clear_cache(self) -> None:
        _MEMBER_CACHE.clear()


permission_manager = PermissionManager()
