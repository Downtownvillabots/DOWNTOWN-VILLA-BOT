# plugins/auto_filter.py
"""
🏨 DOWNTOWN VILLA — AUTO-FILTER PLUGIN (Ultimate)
==================================================
Single entry point that loads all search-related handlers with:
  ✅ per-component load tracking
  ✅ loud failure logging (no more silent Pyrogram skips)
  ✅ optional plugin loading (group_filter, movie_updates)
  ✅ admin health-check command: /autofilter
  ✅ startup banner showing what loaded and how fast

Handlers registered here:
  • media_search.handlers   → PM text search (the auto-filter)
  • plugins.group_filter    → group text search (optional, future)
  • media_search.movie_updates → movie-update channel posts (optional)

Pyrogram walks plugins/ alphabetically. This file is loaded once and
imports the modules whose handlers should be live.
"""
import logging
import time
import traceback
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

logger = logging.getLogger(__name__)

# ═══════════════════════ DIAGNOSTIC — catch-all logger ═══════════════════════
# Runs BEFORE every group-0 handler (negative group fires first).
# Logs every private message. Remove once search is confirmed working.
from pyrogram.types import Message as _DbgMsg

@Client.on_message(filters.private, group=-100)
async def _debug_private(client: Client, message: _DbgMsg):
    try:
        txt = (message.text or "").strip()
        logger.info(
            f"[AF-DEBUG] private msg id={message.id} "
            f"from={message.from_user.id if message.from_user else '?'} "
            f"text={txt[:60]!r}"
        )
    except Exception as e:
        logger.warning(f"[AF-DEBUG] logger error: {e}")


# ═══════════════════════ LOAD STATE ═══════════════════════
class _LoadState:
    """Tracks which sub-components loaded successfully."""

    def __init__(self) -> None:
        self.started_at: float = time.time()
        self.components: Dict[str, Dict[str, Any]] = {}
        self.errors: List[str] = []

    def record(self, name: str, ok: bool, elapsed_ms: float, error: str = "") -> None:
        self.components[name] = {
            "ok": ok,
            "elapsed_ms": round(elapsed_ms, 2),
            "error": error,
        }
        if not ok and error:
            self.errors.append(f"{name}: {error}")

    def summary(self) -> str:
        ok = sum(1 for c in self.components.values() if c["ok"])
        total = len(self.components)
        return f"{ok}/{total} components loaded"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "started_at": self.started_at,
            "uptime_s": round(time.time() - self.started_at, 2),
            "components": self.components,
            "errors": self.errors,
            "summary": self.summary(),
        }


state = _LoadState()


# ═══════════════════════ LOADER HELPER ═══════════════════════
def _load(name: str, import_fn, critical: bool = False):
    """
    Import a module and record status.
    If `critical=True` and import fails, re-raise so Pyrogram stops.
    """
    t0 = time.time()
    try:
        module = import_fn()
        elapsed = (time.time() - t0) * 1000.0
        state.record(name, True, elapsed)
        logger.info(f"[AUTO-FILTER] ✅ {name} loaded in {elapsed:.1f}ms")
        return module
    except Exception as e:
        elapsed = (time.time() - t0) * 1000.0
        err = f"{type(e).__name__}: {e}"
        state.record(name, False, elapsed, err)
        logger.error(f"[AUTO-FILTER] ❌ {name} failed in {elapsed:.1f}ms: {err}")
        logger.debug(traceback.format_exc())
        if critical:
            raise
        return None


# ═══════════════════════ 1. CORE SEARCH HANDLERS (required) ═══════════════════════
def _import_search_handlers():
    from media_search import handlers  # noqa: F401
    return handlers


_handlers = _load("media_search.handlers", _import_search_handlers, critical=True)

if _handlers is None:
    raise RuntimeError(
        "CRITICAL: media_search.handlers failed to load — PM search is disabled"
    )


# ═══════════════════════ 2. GROUP FILTER (optional, future) ═══════════════════════
def _import_group_filter():
    from plugins import group_filter  # noqa: F401
    return group_filter


_group_filter = _load("plugins.group_filter", _import_group_filter, critical=False)


# ═══════════════════════ 3. MOVIE UPDATES (optional) ═══════════════════════
def _import_movie_updates():
    from media_search import movie_updates  # noqa: F401
    return movie_updates


_movie_updates = _load("media_search.movie_updates", _import_movie_updates, critical=False)


# ═══════════════════════ 4. REQUEST CLEANUP (optional) ═══════════════════════
def _import_request_cleanup():
    from media_search import request_cleanup  # noqa: F401
    return request_cleanup


_request_cleanup = _load("media_search.request_cleanup", _import_request_cleanup, critical=False)


# ═══════════════════════ HEALTH CHECK COMMAND ═══════════════════════
@Client.on_message(filters.command("autofilter") & filters.private)
async def cmd_autofilter_status(client: Client, message: Message):
    """Admin diagnostic — show auto-filter load status."""
    # Late import so startup doesn't fail if config is broken
    try:
        from core.config import ADMINS
        uid = message.from_user.id
        is_adm = int(uid) in [
            int(a) for a in ADMINS if str(a).lstrip("-").isdigit()
        ]
    except Exception:
        is_adm = False

    if not is_adm:
        await message.reply_text("⛔ ᴜɴᴀᴜᴛʜᴏʀɪᴢᴇᴅ.")
        return

    info = state.to_dict()
    uptime = info["uptime_s"]
    # Format uptime
    if uptime < 60:
        uptime_str = f"{uptime:.1f}s"
    elif uptime < 3600:
        uptime_str = f"{uptime/60:.1f}m"
    else:
        uptime_str = f"{uptime/3600:.1f}h"

    lines = [
        "🏨 <b>DOWNTOWN VILLA</b>",
        "🔎 <b>AUTO-FILTER STATUS</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"⏱️ ᴜᴘᴛɪᴍᴇ · <code>{uptime_str}</code>",
        f"📊 {info['summary']}",
        "",
        "<b>COMPONENTS:</b>",
    ]

    for name, comp in info["components"].items():
        icon = "✅" if comp["ok"] else "❌"
        lines.append(
            f"{icon} <code>{name}</code> · <code>{comp['elapsed_ms']}ms</code>"
        )
        if not comp["ok"] and comp["error"]:
            lines.append(f"    ⚠️ <code>{comp['error'][:120]}</code>")

    if info["errors"]:
        lines.append("")
        lines.append("<b>ERRORS:</b>")
        for err in info["errors"][:5]:
            lines.append(f"• <code>{err[:140]}</code>")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🔎 ᴛʏᴘᴇ ᴀɴʏ ᴛɪᴛʟᴇ ɪɴ ᴘᴍ ᴛᴏ ꜱᴇᴀʀᴄʜ")

    try:
        await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[AUTO-FILTER] status reply failed: {e}")


# ═══════════════════════ STARTUP BANNER ═══════════════════════
_total_ms = (time.time() - state.started_at) * 1000.0
logger.info("[AUTO-FILTER] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
logger.info(f"[AUTO-FILTER] plugin ready in {_total_ms:.0f}ms")
logger.info(f"[AUTO-FILTER] {state.summary()}")
for _name, _comp in state.components.items():
    _icon = "✅" if _comp["ok"] else "❌"
    logger.info(f"[AUTO-FILTER]   {_icon} {_name} ({_comp['elapsed_ms']}ms)")
if state.errors:
    logger.warning(f"[AUTO-FILTER] {len(state.errors)} error(s):")
    for _err in state.errors:
        logger.warning(f"[AUTO-FILTER]   • {_err}")
logger.info("[AUTO-FILTER] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


# ═══════════════════════ PUBLIC HELPERS ═══════════════════════
def is_ready() -> bool:
    """Return True if core search handlers loaded successfully."""
    return _handlers is not None


def get_state() -> Dict[str, Any]:
    """Return a snapshot of load state (for admin dashboards)."""
    return state.to_dict()


def get_errors() -> List[str]:
    """Return load errors, if any."""
    return list(state.errors)
