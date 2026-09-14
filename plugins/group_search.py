# plugins/group_search.py
"""
DOWNTOWN VILLA — Group search handler.

Registers the group auto-filter. Separate from plugins/auto_filter.py
which only handles PM + callbacks.
"""

import logging
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] module loaded")


@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-10,   # run after diag (-999) but before default
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
            logger.info("[GROUP-SEARCH] auto_ffilter is OFF for this group")
            return

        # 2. Search
        from services.media_service import get_search_results
        files, offset, total = await get_search_results(
            chat_id=message.chat.id,
            query=message.text.lower(),
            offset=0,
            filter=True,
        )
        logger.info(f"[GROUP-SEARCH] files={len(files) if files else 0} total={total}")

        if not files:
            logger.info("[GROUP-SEARCH] no results — skipping reply")
            return

        # 3. Build buttons
        btn = []
        for f in files:
            fid = f.get("file_id") or f.get("_id")
            fname = str(f.get("file_name", "?"))[:60]
            btn.append([InlineKeyboardButton(
                text=f"📥 {fname}",
                callback_data=f"file#{fid}",
            )])

        # 4. Reply
        await message.reply_text(
            f"<b>🎬 Found <code>{total}</code> result(s) for "
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
        return await q.answer("❌ ɪɴᴠᴀʟɪᴅ ᴅᴀᴛᴀ", show_alert=True)

    # Use bot username to build deep link
    try:
        me = await client.get_me()
        chat_id = q.message.chat.id
        deep_link = f"https://t.me/{me.username}?start=file_{chat_id}_{file_id}"
        await q.answer(url=deep_link)
    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] deep-link failed: {e}")
        await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
