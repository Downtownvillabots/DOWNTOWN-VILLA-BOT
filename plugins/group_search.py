# plugins/group_search.py
"""
DOWNTOWN VILLA — Group auto-filter.

Thin wrapper around media_search.handlers._handle_search.
Only runs for group text messages. Checks per-group settings first,
then delegates to the existing search flow (search → file list → delivery to PM).
"""

import logging
from pyrogram import Client, filters

logger = logging.getLogger(__name__)
logger.info("[GROUP-SEARCH] module loaded")


@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-10,
)
async def group_search_handler(client: Client, message):
    logger.info(
        f"[GROUP-SEARCH] chat={message.chat.id} "
        f"user={message.from_user.id if message.from_user else '?'} "
        f"text={message.text!r}"
    )

    try:
        # 1) Check per-group settings
        try:
            from services.settings_service import get_settings
            s = await get_settings(message.chat.id)
            if not s.get("auto_ffilter", True):
                logger.info("[GROUP-SEARCH] auto_ffilter is OFF for this group — skipping")
                return
        except Exception as e:
            logger.warning(f"[GROUP-SEARCH] settings check failed: {e}")
            # Continue anyway — better to search than to skip

        # 2) Delegate to the existing media_search handler
        from media_search.handlers import _handle_search
        await _handle_search(client, message, message.text, is_group=True)
        logger.info("[GROUP-SEARCH] handed off to _handle_search ✅")

    except ImportError as e:
        logger.error(f"[GROUP-SEARCH] import failed: {e}")
    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] crashed: {e}")
