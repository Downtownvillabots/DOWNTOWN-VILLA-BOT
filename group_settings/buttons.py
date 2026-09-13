"""
Result Button Manager.
Per-group configurable buttons on file-delivery messages.

Rule: max 8 buttons. Order preserved by `position`.
"""
import logging
import secrets
from typing import Any, Dict, List, Optional

from group_settings.manager import config_manager

logger = logging.getLogger(__name__)

MAX_BUTTONS = 8


class ResultButtonManager:
    async def list_buttons(self, chat_id: int) -> List[Dict[str, Any]]:
        cfg = await config_manager.get_config(chat_id)
        buttons = cfg.get("result_buttons") or []
        # Sort by position
        return sorted(buttons, key=lambda b: b.get("position", 999))

    async def add_button(self, chat_id: int, name: str, url: str) -> Optional[Dict[str, Any]]:
        buttons = await self.list_buttons(chat_id)
        if len(buttons) >= MAX_BUTTONS:
            logger.warning(f"[BTN] add rejected — max {MAX_BUTTONS} reached for {chat_id}")
            return None
        if not name or not url:
            return None
        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
            return None

        new_btn = {
            "id": secrets.token_hex(6),
            "name": name.strip()[:60],
            "url": url.strip(),
            "enabled": True,
            "position": (max([b.get("position", 0) for b in buttons]) + 1) if buttons else 1,
        }
        buttons.append(new_btn)
        await config_manager.set_field(chat_id, "result_buttons", buttons)
        return new_btn

    async def edit_button(self, chat_id: int, button_id: str,
                          new_name: Optional[str] = None,
                          new_url: Optional[str] = None,
                          new_enabled: Optional[bool] = None) -> bool:
        buttons = await self.list_buttons(chat_id)
        found = False
        for b in buttons:
            if b.get("id") == button_id:
                if new_name is not None:
                    b["name"] = new_name.strip()[:60]
                if new_url is not None:
                    b["url"] = new_url.strip()
                if new_enabled is not None:
                    b["enabled"] = bool(new_enabled)
                found = True
                break
        if not found:
            return False
        await config_manager.set_field(chat_id, "result_buttons", buttons)
        return True

    async def remove_button(self, chat_id: int, button_id: str) -> bool:
        buttons = await self.list_buttons(chat_id)
        filtered = [b for b in buttons if b.get("id") != button_id]
        if len(filtered) == len(buttons):
            return False
        # Re-number
        for i, b in enumerate(filtered, 1):
            b["position"] = i
        await config_manager.set_field(chat_id, "result_buttons", filtered)
        return True

    async def reorder(self, chat_id: int, new_order: List[str]) -> bool:
        """new_order = list of button IDs in desired order."""
        buttons = await self.list_buttons(chat_id)
        id_map = {b.get("id"): b for b in buttons}
        reordered = []
        for idx, bid in enumerate(new_order, 1):
            if bid in id_map:
                b = id_map.pop(bid)
                b["position"] = idx
                reordered.append(b)
        # Append any stragglers
        for b in id_map.values():
            b["position"] = len(reordered) + 1
            reordered.append(b)
        await config_manager.set_field(chat_id, "result_buttons", reordered)
        return True

    async def move_up(self, chat_id: int, button_id: str) -> bool:
        buttons = await self.list_buttons(chat_id)
        idx = next((i for i, b in enumerate(buttons) if b.get("id") == button_id), -1)
        if idx <= 0:
            return False
        buttons[idx - 1], buttons[idx] = buttons[idx], buttons[idx - 1]
        for i, b in enumerate(buttons, 1):
            b["position"] = i
        await config_manager.set_field(chat_id, "result_buttons", buttons)
        return True

    async def move_down(self, chat_id: int, button_id: str) -> bool:
        buttons = await self.list_buttons(chat_id)
        idx = next((i for i, b in enumerate(buttons) if b.get("id") == button_id), -1)
        if idx < 0 or idx >= len(buttons) - 1:
            return False
        buttons[idx + 1], buttons[idx] = buttons[idx], buttons[idx + 1]
        for i, b in enumerate(buttons, 1):
            b["position"] = i
        await config_manager.set_field(chat_id, "result_buttons", buttons)
        return True

    async def toggle_enabled(self, chat_id: int, button_id: str) -> Optional[bool]:
        buttons = await self.list_buttons(chat_id)
        for b in buttons:
            if b.get("id") == button_id:
                b["enabled"] = not b.get("enabled", True)
                await config_manager.set_field(chat_id, "result_buttons", buttons)
                return b["enabled"]
        return None

    async def reset_buttons(self, chat_id: int) -> bool:
        """Restore default buttons (SHARE + UPDATES)."""
        from core.config import UPDATE_CHNL_LNK
        defaults = [
            {"id": secrets.token_hex(6), "name": "📤 SHARE FILE",
             "url": "https://t.me/share/url?url=https://t.me/&text=Check%20this",
             "enabled": True, "position": 1},
            {"id": secrets.token_hex(6), "name": "📢 UPDATES",
             "url": UPDATE_CHNL_LNK or "https://t.me/",
             "enabled": True, "position": 2},
        ]
        return await config_manager.set_field(chat_id, "result_buttons", defaults)


button_manager = ResultButtonManager()
