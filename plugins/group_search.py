# plugins/group_search.py
"""
DOWNTOWN VILLA — Group search handler.
Uses existing media_search/ package for the search.
"""

import logging
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] module loaded")


@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-10,
)
async def group_search(client: Client, message):
    logger.info(
        f"[GROUP-SEARCH] from={message.from_user.id if message.from_user else '?'} "
        f"chat={message.chat.id} text={message.text!r}"
    )

    try:
        # 1. Check settings
        from services.settings_service import get_settings
        s = await get_settings(message.chat.id)
        if not s.get("auto_ffilter", True):
            logger.info("[GROUP-SEARCH] auto_ffilter OFF for this group")
            return

        # 2. Search via your existing media_search package
        try:
            from media_search.handlers import search
        except ImportError:
            # try alternative names
            try:
                from media_search import search
            except ImportError:
                from media_search.handlers import perform_search as search

        # Call whatever the search function is — try common signatures
        result = None
        try:
            result = await search(message.text, message.chat.id)
        except TypeError:
            result = await search(query=message.text, chat_id=message.chat.id)
        except Exception as e:
            logger.exception(f"[GROUP-SEARCH] search call failed: {e}")
            return

        files = []
        total = 0
        if isinstance(result, tuple):
            if len(result) >= 3:
                files, _, total = result[0], result[1], result[2]
            elif len(result) >= 1:
                files = result[0] or []
        elif isinstance(result, list):
            files = result
        elif hasattr(result, "files"):
            files = result.files or []
            total = getattr(result, "total", len(files))

        logger.info(f"[GROUP-SEARCH] files={len(files)} total={total}")

        if not files:
            logger.info("[GROUP-SEARCH] no results")
            return

        # 3. Build buttons
        btn = []
        for f in files[:10]:
            fid = None
            fname = "?"
            if isinstance(f, dict):
                fid = f.get("file_id") or f.get("_id")
                fname = str(f.get("file_name", "?"))[:60]
            else:
                fid = getattr(f, "file_id", None) or getattr(f, "_id", None)
                fname = str(getattr(f, "file_name", "?"))[:60]
            if fid:
                btn.append([InlineKeyboardButton(
                    text=f"📥 {fname}",
                    callback_data=f"file#{fid}",
                )])

        if not btn:
            return

        # 4. Reply
        await message.reply_text(
            f"<b>🎬 Found <code>{total or len(files)}</code> result(s) for "
            f"<code>{message.text}</code></b>\n\n"
            f"👇 Click a file to receive it in PM.",
            reply_markup=InlineKeyboardMarkup(btn),
            parse_mode=enums.ParseMode.HTML,
        )
        logger.info("[GROUP-SEARCH] reply sent ✅")

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] crashed: {e}")


# ═══════════════════════════════════════════════════════════
# Callback: file#{file_id}  →  redirect to PM
# ═══════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^file#"))
async def file_button_callback(client: Client, q):
    try:
        _, file_id = q.data.split("#", 1)
    except Exception:
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)

    try:
        me = await client.get_me()
        chat_id = q.message.chat.id
        deep_link = f"https://t.me/{me.username}?start=file_{chat_id}_{file_id}"
        await q.answer(url=deep_link)
    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] deep-link failed: {e}")
        await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
