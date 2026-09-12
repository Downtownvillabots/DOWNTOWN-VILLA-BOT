"""
Force-subscription check.
Supports 1..N required channels (dynamic).
Uses core.config.AUTH_CHANNELS.
"""
import logging
from typing import List, Tuple

from pyrogram import Client
from pyrogram.errors import UserNotParticipant, ChatAdminRequired, ChannelPrivate

from core.config import AUTH_CHANNELS
from media_search.config import FORCE_SUB_ENABLED

logger = logging.getLogger(__name__)


class SubscriptionChecker:
    @property
    def enabled(self) -> bool:
        return FORCE_SUB_ENABLED and bool(AUTH_CHANNELS)

    @property
    def channels(self) -> List[int]:
        return list(AUTH_CHANNELS) if AUTH_CHANNELS else []

    async def is_subscribed(self, client: Client, user_id: int) -> Tuple[bool, List[int]]:
        """
        Returns (all_joined, missing_channel_ids).
        If not enabled, returns (True, []).
        """
        if not self.enabled:
            return True, []

        missing: List[int] = []
        for ch in self.channels:
            try:
                member = await client.get_chat_member(ch, user_id)
                if member.status in ("left", "kicked", "banned"):
                    missing.append(ch)
            except UserNotParticipant:
                missing.append(ch)
            except (ChatAdminRequired, ChannelPrivate):
                # Can't verify — treat as satisfied to avoid blocking users
                continue
            except Exception as e:
                logger.warning(f"[SUB] check failed for {ch}: {type(e).__name__}: {e}")
                continue

        return (len(missing) == 0), missing


subscription = SubscriptionChecker()
