# plugins/_diag_group.py
"""
DOWNTOWN VILLA — Group search diagnostic.
DELETE after debugging.
"""

import logging
from pyrogram import Client, filters, enums
from pyrogram.types import Message

logger = logging.getLogger(__name__)
logger.info("[DIAG] _diag_group.py loaded")   # ← confirms file is loaded


@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-999,
)
async def diag_group_search(client: Client, message: Message):
    logger.info(
        f"[DIAG] group msg | chat={message.chat.id} "
        f"type={message.chat.type} "
        f"user={message.from_user.id if message.from_user else '?'} "
        f"text={message.text!r}"
    )

    # Check DB
    from database import db_manager
    try:
        user_db = db_manager.get_user_db() if hasattr(db_manager, "get_user_db") else None
        media_db = db_manager.get_media_db() if hasattr(db_manager, "get_media_db") else None
        logger.info(f"[DIAG] user_db={'OK' if user_db is not None else 'None'} "
                    f"media_db={'OK' if media_db is not None else 'None'}")
    except Exception as e:
        logger.error(f"[DIAG] db_manager check failed: {e}")

    # Group settings
    try:
        from database.users_chats_db import db as legacy_db
        settings = await legacy_db.get_settings(message.chat.id)
        logger.info(f"[DIAG] auto_ffilter={settings.get('auto_ffilter')} "
                    f"button={settings.get('button')}")
    except Exception as e:
        logger.warning(f"[DIAG] settings check failed: {e}")

    # Media count
    try:
        from database import db_manager as dm
        db = dm.get_media_db() if hasattr(dm, "get_media_db") else None
        if db is not None:
            total = await db["media_files"].count_documents({})
            logger.info(f"[DIAG] media_files count={total}")
        else:
            logger.error("[DIAG] media DB is None")
    except Exception as e:
        logger.warning(f"[DIAG] count check failed: {e}")

    # Search
    try:
        from services.media_service import get_search_results
        files, offset, total = await get_search_results(
            chat_id=message.chat.id,
            query=message.text.lower(),
            offset=0,
            filter=True,
        )
        logger.info(f"[DIAG] get_search_results → files={len(files) if files else 0} "
                    f"total={total} offset={offset}")
    except ImportError as e:
        logger.error(f"[DIAG] services.media_service missing: {e}")
    except Exception as e:
        logger.exception(f"[DIAG] get_search_results crashed: {e}")
