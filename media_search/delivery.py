"""
Telegram file delivery. Sends file_id, warns, auto-deletes.
"""
import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import FloodWait, MessageNotModified

from media_search.auto_delete import auto_delete, AUTO_DELETE_WARNING
from media_search.caption import caption_renderer
from media_search.models import FileHit

logger = logging.getLogger(__name__)

_locks: Dict[int, Dict[str, float]] = {}
_LOCK_TTL = 3.0


class DeliveryService:

    def _check_lock(self, user_id: int, file_id: str) -> bool:
        now = time.time()
        ul = _locks.setdefault(user_id, {})
        last = ul.get(file_id, 0.0)
        if now - last < _LOCK_TTL:
            return False
        for k in list(ul.keys()):
            if now - ul[k] > _LOCK_TTL * 4:
                ul.pop(k, None)
        ul[file_id] = now
        return True

    async def send_file(self, client: Client, chat_id: int, hit: FileHit,
                        group_id: Optional[int] = None) -> Tuple[bool, str]:
        if not hit.file_id:
            return False, "❌ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ."
        if not self._check_lock(chat_id, hit.file_id):
            return False, "⏳ ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ ᴀ ᴍᴏᴍᴇɴᴛ."

        sent_msg = None
        try:
            bot_username = getattr(client, "username", "") or ""
            caption = await caption_renderer.render_file(hit.__dict__, group_id, bot_username)

            sent_msg = await client.send_cached_media(
                chat_id=chat_id,
                file_id=hit.file_id,
                caption=caption,
            )
            logger.info(
                f"[DELIVERY] sent file_id={hit.file_id[:20]}… "
                f"to={chat_id}"
            )

            # Schedule delete + warning
            if auto_delete.enabled and sent_msg:
                warning_msg = None
                try:
                    warning_msg = await client.send_message(
                        chat_id=chat_id,
                        text=AUTO_DELETE_WARNING.format(minutes=auto_delete.minutes),
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
                await auto_delete.schedule(
                    client, chat_id, sent_msg.id,
                    extra_message_ids=[warning_msg.id] if warning_msg else [],
                )
            return True, ""
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            return False, f"⏳ ʀᴀᴛᴇ ʟɪᴍɪᴛ · ᴛʀʏ ɪɴ {e.value}s."
        except MessageNotModified:
            return True, ""
        except Exception as e:
            logger.warning(f"[DELIVERY] failed: {type(e).__name__}: {e}")
            return False, "❌ ꜰᴀɪʟᴇᴅ ᴛᴏ ꜱᴇɴᴅ ꜰɪʟᴇ."

    async def send_batch(self, client, chat_id, hits, group_id=None, max_files=10):
        sent = failed = 0
        for hit in hits[:max_files]:
            ok, _ = await self.send_file(client, chat_id, hit, group_id)
            if ok: sent += 1
            else: failed += 1
            await asyncio.sleep(0.8)
        return sent, failed


delivery = DeliveryService()
