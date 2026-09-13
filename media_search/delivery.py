"""
Telegram file delivery.
- Builds caption from file metadata (title, size, quality, codec, audio, subtitle)
- Ignores the original channel caption entirely
- Adds SHARE + UPDATES buttons
- Schedules auto-delete + warning
"""
import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
from urllib.parse import quote_plus

from pyrogram import Client
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from media_search.auto_delete import auto_delete, AUTO_DELETE_WARNING
from media_search.models import FileHit

logger = logging.getLogger(__name__)


# ═══════════════════════ CAPTION BUILDER ═══════════════════════
def _clean_caption(hit: FileHit) -> str:
    """Build a caption from file metadata only. No original channel caption."""
    from services.formatting import clean_filename, get_size

    clean_name = clean_filename(hit.file_name, max_len=80) or hit.title or "?"

    lines = [f"🎬 <b>{clean_name}</b>"]
    if hit.year:
        lines.append(f"📅 {hit.year}")

    lines.append("")

    if hit.quality:
        lines.append(f"🎞️ Qᴜᴀʟɪᴛʏ: <code>{hit.quality.upper()}</code>")
    if hit.codec:
        lines.append(f"🧬 Cᴏᴅᴇᴄ: <code>{hit.codec.upper()}</code>")
    if hit.audio_languages:
        lines.append(f"🔊 Aᴜᴅɪᴏ: <code>{', '.join(hit.audio_languages)}</code>")
    if hit.subtitle_languages:
        lines.append(f"📝 Sᴜʙᴛɪᴛʟᴇ: <code>{', '.join(hit.subtitle_languages)}</code>")
    elif hit.has_subtitle:
        lines.append(f"📝 Sᴜʙᴛɪᴛʟᴇ: <code>YES</code>")
    if hit.file_size:
        lines.append(f"💾 Sɪᴢᴇ: <code>{get_size(hit.file_size)}</code>")

    lines.append("")
    lines.append("⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>")
    return "\n".join(lines)


# ═══════════════════════ SHARE + UPDATES BUTTONS ═══════════════════════
def _build_buttons(bot_username: str, title: str) -> InlineKeyboardMarkup:
    from core.config import UPDATE_CHNL_LNK

    share_text = f"🎬 {title} — via @{bot_username}"
    share_url = (
        f"https://t.me/share/url?"
        f"url=https://t.me/{bot_username}&"
        f"text={quote_plus(share_text)}"
    )
    rows = [[
        InlineKeyboardButton("📤 SHARE", url=share_url),
        InlineKeyboardButton("📢 UPDATES", url=UPDATE_CHNL_LNK or "https://t.me/"),
    ]]
    return InlineKeyboardMarkup(rows)


# ═══════════════════════ DELIVERY SERVICE ═══════════════════════
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
            caption = _clean_caption(hit)
            bot_username = getattr(client, "username", "") or "Downtown_Villa_The_Ultimate_Bot"
            kb = _build_buttons(bot_username, hit.title or hit.file_name or "file")

            sent_msg = await client.send_cached_media(
                chat_id=chat_id,
                file_id=hit.file_id,
                caption=caption,
                reply_markup=kb,
            )
            logger.info(f"[DELIVERY] sent file_id={hit.file_id[:20]}… to={chat_id}")

            # Auto-delete + warning
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
            if ok:
                sent += 1
            else:
                failed += 1
            await asyncio.sleep(0.8)
        return sent, failed


delivery = DeliveryService()
