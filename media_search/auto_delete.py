"""
Auto-delete scheduler for sent files.
Configurable via env AUTO_DELETE_MINUTES (default 10).
Sends a warning message right after each file.
Never deletes system messages or admin messages.
"""
import asyncio
import logging
import os
import time
from typing import Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import FloodWait, MessageDeleteForbidden, MessageIdInvalid

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# Configurable values
AUTO_DELETE_ENABLED = os.getenv("AUTO_DELETE_ENABLED", "True").lower() in ("1", "true", "yes", "on")
AUTO_DELETE_MINUTES = _env_int("AUTO_DELETE_MINUTES", 10)
AUTO_DELETE_WARNING = os.getenv(
    "AUTO_DELETE_WARNING",
    "⚠️ ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ <b>{minutes} ᴍɪɴᴜᴛᴇꜱ</b>.\n"
    "ᴘʟᴇᴀꜱᴇ ꜱᴀᴠᴇ ᴏʀ ꜱʜᴀʀᴇ ɪᴛ ɴᴏᴡ."
)


class AutoDeleteManager:
    """
    Schedules deletion of (chat_id, message_id) pairs.
    Tracks the warning message too so both get cleaned up together.
    """
    def __init__(self):
        self._tasks: Dict[Tuple[int, int], asyncio.Task] = {}

    @property
    def enabled(self) -> bool:
        return AUTO_DELETE_ENABLED and AUTO_DELETE_MINUTES > 0

    @property
    def minutes(self) -> int:
        return AUTO_DELETE_MINUTES

    def _key(self, chat_id: int, message_id: int) -> Tuple[int, int]:
        return (chat_id, message_id)

    async def schedule(self, client: Client, chat_id: int, message_id: int,
                       extra_message_ids: Optional[List[int]] = None,
                       minutes: Optional[int] = None) -> None:
        """
        Schedule deletion of a file message + optional extra messages
        (like the warning message) after `minutes`.
        """
        if not self.enabled:
            return
        m = minutes if minutes is not None else self.minutes
        key = self._key(chat_id, message_id)

        # Cancel existing task for the same message
        old = self._tasks.pop(key, None)
        if old and not old.done():
            old.cancel()

        task = asyncio.create_task(
            self._delete_after(client, chat_id, message_id, extra_message_ids or [], m)
        )
        self._tasks[key] = task
        logger.info(
            f"[AUTODEL] scheduled chat={chat_id} msg={message_id} "
            f"extra={len(extra_message_ids or [])} in {m}m"
        )

    async def _delete_after(self, client: Client, chat_id: int, message_id: int,
                            extra_ids: List[int], minutes: int) -> None:
        try:
            await asyncio.sleep(max(30, minutes * 60))
            # Delete the extra messages first (warnings)
            for mid in extra_ids:
                try:
                    await client.delete_messages(chat_id, mid)
                except (MessageDeleteForbidden, MessageIdInvalid):
                    pass
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                except Exception:
                    pass
            # Then the file
            try:
                await client.delete_messages(chat_id, message_id)
                logger.info(f"[AUTODEL] deleted chat={chat_id} msg={message_id}")
            except (MessageDeleteForbidden, MessageIdInvalid):
                logger.debug(f"[AUTODEL] cannot delete chat={chat_id} msg={message_id}")
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    await client.delete_messages(chat_id, message_id)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"[AUTODEL] delete failed: {e}")
        except asyncio.CancelledError:
            return
        finally:
            self._tasks.pop(self._key(chat_id, message_id), None)

    def cancel_all_for_chat(self, chat_id: int) -> int:
        """Cancel all pending auto-deletes for a chat (e.g. on bot stop)."""
        n = 0
        for (cid, mid), task in list(self._tasks.items()):
            if cid == chat_id:
                if not task.done():
                    task.cancel()
                self._tasks.pop((cid, mid), None)
                n += 1
        return n

    async def shutdown(self) -> None:
        """Cancel all scheduled deletes (called at bot shutdown)."""
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        # Give tasks a moment to cancel
        if self._tasks:
            await asyncio.sleep(0.1)
        self._tasks.clear()


auto_delete = AutoDeleteManager()
