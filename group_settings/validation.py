"""
Group Validation Manager.
Ensures a group can be registered:
- exists
- bot can access
- bot is admin
- has required permissions
- not already registered
"""
import logging
from typing import Any, Dict

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import ChatAdminRequired, ChannelPrivate, PeerIdInvalid

from group_settings.manager import config_manager

logger = logging.getLogger(__name__)


class GroupValidationManager:
    async def validate(self, client: Client, chat_id: int,
                       check_registered: bool = True) -> Dict[str, Any]:
        """
        Returns dict:
          {ok: bool, title: str|None, username: str|None,
           bot_present: bool, bot_admin: bool, error: str|None}
        """
        out: Dict[str, Any] = {
            "ok": False, "title": None, "username": None,
            "bot_present": False, "bot_admin": False,
            "error": None, "chat_id": chat_id,
        }

        # 1. Chat exists
        try:
            chat = await client.get_chat(chat_id)
        except (PeerIdInvalid, ChannelPrivate) as e:
            out["error"] = f"INVALID_OR_INACCESSIBLE: {type(e).__name__}"
            return out
        except Exception as e:
            out["error"] = f"CHAT_LOOKUP_FAILED: {type(e).__name__}"
            return out

        # 2. Must be a group
        if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            out["error"] = "NOT_A_GROUP"
            return out

        out["title"] = chat.title
        out["username"] = chat.username

        # 3. Bot is member
        try:
            me = await client.get_me()
            member = await client.get_chat_member(chat_id, me.id)
        except Exception:
            out["error"] = "BOT_NOT_PRESENT"
            return out
        out["bot_present"] = True

        # 4. Bot is admin
        status = getattr(member, "status", None)
        if hasattr(status, "name"):
            status = status.name.lower()
        else:
            status = str(status).lower()

        if status not in ("administrator", "creator", "owner"):
            out["error"] = "BOT_NOT_ADMIN"
            return out

        out["bot_admin"] = True

        # 5. Already registered?
        if check_registered:
            existing = await config_manager.get_raw(chat_id)
            if existing and existing.get("title"):
                # Already registered — still OK to re-verify, but report
                out["already_registered"] = True

        out["ok"] = True
        return out


validation_manager = GroupValidationManager()
