# plugins/group_search.py
"""
DOWNTOWN VILLA — Group search handler.

Auto-discovers the search function inside the media_search package
at runtime, so we don't need to hardcode its name.
"""

import importlib
import inspect
import logging

from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] module loaded")


# ═══════════════════════════════════════════════════════════
# Discover the search function dynamically
# ═══════════════════════════════════════════════════════════
_SEARCH_FN = None
_SEARCH_FN_PATH = None


def _find_search_function():
    """Look inside media_search package for an async search function."""
    global _SEARCH_FN, _SEARCH_FN_PATH
    if _SEARCH_FN is not None:
        return _SEARCH_FN

    candidates = [
        "media_search.handlers",
        "media_search.search",
        "media_search.core",
        "media_search",
    ]

    for mod_path in candidates:
        try:
            mod = importlib.import_module(mod_path)
        except ImportError:
            continue

        # Log what this module exposes
        members = [n for n in dir(mod) if not n.startswith("_")]
        logger.info(f"[GROUP-SEARCH] scanning {mod_path} → {members[:20]}")

        # Look for async function whose name hints at search
        for name, obj in inspect.getmembers(mod, inspect.iscoroutinefunction):
            if name.startswith("_"):
                continue
            low = name.lower()
            if any(tok in low for tok in ("search", "find", "query", "filter")):
                _SEARCH_FN = obj
                _SEARCH_FN_PATH = f"{mod_path}.{name}"
                logger.info(f"[GROUP-SEARCH] found search fn: {_SEARCH_FN_PATH}")
                return obj

        # Also look for a nested handlers/executor object with .search
        for name in members:
            try:
                sub = getattr(mod, name)
            except Exception:
                continue
            if inspect.ismodule(sub):
                continue
            inner_search = getattr(sub, "search", None) or getattr(sub, "perform_search", None)
            if inner_search and inspect.iscoroutinefunction(inner_search):
                _SEARCH_FN = inner_search
                _SEARCH_FN_PATH = f"{mod_path}.{name}.search"
                logger.info(f"[GROUP-SEARCH] found search fn: {_SEARCH_FN_PATH}")
                return inner_search

    logger.error("[GROUP-SEARCH] could not find any search function")
    return None


async def _call_search(fn, query: str, chat_id: int):
    """
    Try calling the search function with several signatures.
    Returns a normalized (files, total) tuple.
    """
    sig = inspect.signature(fn)
    param_names = list(sig.parameters.keys())
    logger.info(f"[GROUP-SEARCH] calling {_SEARCH_FN_PATH} params={param_names}")

    # Try several common calling conventions
    call_attempts = [
        # (query, chat_id)
        lambda: fn(query, chat_id),
        # (chat_id, query)
        lambda: fn(chat_id, query),
        # keyword args
        lambda: fn(query=query, chat_id=chat_id),
        # just query
        lambda: fn(query),
        # just chat_id and text
        lambda: fn(chat_id=chat_id, text=query),
        # text first
        lambda: fn(text=query, chat_id=chat_id),
    ]

    last_err = None
    for i, attempt in enumerate(call_attempts):
        try:
            result = await attempt()
            logger.info(f"[GROUP-SEARCH] signature #{i+1} worked")
            return _normalize_result(result)
        except TypeError as e:
            last_err = e
            continue
        except Exception as e:
            logger.exception(f"[GROUP-SEARCH] call #{i+1} raised: {e}")
            return [], 0

    logger.error(f"[GROUP-SEARCH] all signatures failed: {last_err}")
    return [], 0


def _normalize_result(result):
    """Convert search result to (files, total)."""
    if result is None:
        return [], 0
    if isinstance(result, tuple):
        if len(result) >= 3:
            files = result[0] or []
            total = result[2] if isinstance(result[2], int) else len(files)
            return list(files), int(total)
        if len(result) == 2:
            return list(result[0] or []), len(result[0] or [])
        if len(result) == 1:
            return list(result[0] or []), len(result[0] or [])
    if isinstance(result, list):
        return result, len(result)
    if isinstance(result, dict):
        files = result.get("files") or result.get("results") or []
        total = result.get("total") or len(files)
        return list(files), int(total)
    if hasattr(result, "files"):
        files = result.files or []
        return list(files), int(getattr(result, "total", len(files)))
    return [], 0


# ═══════════════════════════════════════════════════════════
# Group handler
# ═══════════════════════════════════════════════════════════
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
        # 1. Settings
        from services.settings_service import get_settings
        s = await get_settings(message.chat.id)
        if not s.get("auto_ffilter", True):
            logger.info("[GROUP-SEARCH] auto_ffilter OFF for this group")
            return

        # 2. Find search function
        fn = _find_search_function()
        if fn is None:
            logger.error("[GROUP-SEARCH] no search function — aborting")
            return

        # 3. Run search
        files, total = await _call_search(fn, message.text, message.chat.id)
        logger.info(f"[GROUP-SEARCH] files={len(files)} total={total}")

        if not files:
            logger.info("[GROUP-SEARCH] no results")
            return

        # 4. Build buttons
        btn = []
        for f in files[:10]:
            if isinstance(f, dict):
                fid = f.get("file_id") or f.get("_id")
                fname = str(f.get("file_name", "?"))[:60]
            else:
                fid = getattr(f, "file_id", None) or getattr(f, "_id", None)
                fname = str(getattr(f, "file_name", "?"))[:60]
            if fid:
                btn.append([InlineKeyboardButton(
                    text=f"📥 {fname}",
                    callback_data=f"gfile#{fid}",
                )])

        if not btn:
            logger.warning("[GROUP-SEARCH] no valid file_ids to show")
            return

        # 5. Reply
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
# Callback: gfile#{file_id} → deep-link to PM
# ═══════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^gfile#"))
async def gfile_callback(client: Client, q):
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


# ═══════════════════════════════════════════════════════════
# Startup: try to discover once (so we see it in logs)
# ═══════════════════════════════════════════════════════════
try:
    _fn = _find_search_function()
    if _fn:
        logger.info(f"[GROUP-SEARCH] discovered search fn at import: {_SEARCH_FN_PATH}")
    else:
        logger.warning("[GROUP-SEARCH] no search fn at import time — will retry on first message")
except Exception as e:
    logger.warning(f"[GROUP-SEARCH] startup discovery error: {e}")
