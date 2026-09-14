# plugins/_diag_group.py
"""
DOWNTOWN VILLA — Group search diagnostic (extended).
DELETE after debugging.
"""

import logging
from pyrogram import Client, filters, enums
from pyrogram.types import Message

logger = logging.getLogger(__name__)
logger.info("[DIAG] _diag_group.py loaded")


@Client.on_message(
    filters.group & filters.text & filters.incoming & ~filters.regex(r"^/"),
    group=-999,
)
async def diag_group_search(client: Client, message: Message):
    logger.info(
        f"[DIAG] group msg | chat={message.chat.id} "
        f"user={message.from_user.id if message.from_user else '?'} "
        f"text={message.text!r}"
    )

    # DB check
    from database import db_manager
    user_db = None
    media_db = None
    try:
        user_db = db_manager.get_user_db() if hasattr(db_manager, "get_user_db") else None
        media_db = db_manager.get_media_db() if hasattr(db_manager, "get_media_db") else None
    except Exception:
        pass
    logger.info(f"[DIAG] user_db={'OK' if user_db else 'None'} media_db={'OK' if media_db else 'None'}")

    # Settings
    try:
        from services.settings_service import get_settings
        s = await get_settings(message.chat.id)
        logger.info(
            f"[DIAG] settings | auto_ffilter={s.get('auto_ffilter')} "
            f"button={s.get('button')} imdb={s.get('imdb')} "
            f"spell_check={s.get('spell_check')} auto_delete={s.get('auto_delete')}"
        )
    except Exception as e:
        logger.exception(f"[DIAG] settings check failed: {e}")

    # Bot admin rights in this chat
    try:
        me = await client.get_me()
        member = await client.get_chat_member(message.chat.id, me.id)
        status = getattr(member, "status", None)
        status = status.name.lower() if hasattr(status, "name") else str(status).lower()
        can_send = getattr(member, "can_send_messages", None)
        can_media = getattr(member, "can_send_media_messages", None)
        logger.info(f"[DIAG] bot status={status} can_send={can_send} can_media={can_media}")
    except Exception as e:
        logger.exception(f"[DIAG] bot member check failed: {e}")

    # Media count
    try:
        from database import db_manager as dm
        db = dm.get_media_db() if hasattr(dm, "get_media_db") else None
        if db is not None:
            total = await db["media_files"].count_documents({})
            logger.info(f"[DIAG] media_files count={total}")
    except Exception as e:
        logger.warning(f"[DIAG] count check failed: {e}")

    # Search directly
    try:
        from services.media_service import get_search_results
        files, offset, total = await get_search_results(
            chat_id=message.chat.id,
            query=message.text.lower(),
            offset=0,
            filter=True,
        )
        logger.info(f"[DIAG] search → files={len(files) if files else 0} total={total}")
    except Exception as e:
        logger.exception(f"[DIAG] search crashed: {e}")

    # Run the actual group handler manually to see if it crashes
    try:
        from plugins.auto_filter import give_filter
        logger.info("[DIAG] invoking group auto_filter manually...")
        await give_filter(client, message)
        logger.info("[DIAG] group auto_filter completed OK")
    except ImportError as e:
        logger.error(f"[DIAG] auto_filter handler not found: {e}")
    except Exception as e:
        logger.exception(f"[DIAG] auto_filter raised: {e}")
