"""
Auto-filter handlers — the whole search UI flow.
Registered via plugins/auto_filter.py.
"""
import logging
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode, ChatType
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from media_search.caption import caption_renderer
from media_search.config import SEARCH_PAGE_SIZE
from media_search.delivery import delivery
from media_search.engine import engine
from media_search.keyboards import (
    main_menu, back_close, candidates, languages, qualities,
    files as files_kb, seasons, episodes, sub_required, no_results,
)
from media_search.metadata import metadata_provider
from media_search.models import FileHit, TitleCandidate
from media_search.normalizer import parse_query
from media_search.ranker import ranker
from media_search.requests import requests as request_repo
from media_search.sessions import sessions
from media_search.subscription import subscription

logger = logging.getLogger(__name__)

DIV = "━" * 26


def _is_authorized(msg_or_cb) -> bool:
    return getattr(msg_or_cb.from_user, "id", None) is not None


def _human_size(size: Optional[int]) -> str:
    if not size:
        return "0 B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


# ═══════════════════════ SEARCH COMMAND ═══════════════════════
@Client.on_message(filters.command(["search", "s"]) & (filters.private | filters.group))
async def cmd_search(client: Client, message: Message):
    """Main entry: /search opens menu, /search <query> runs an immediate search."""
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].strip():
        await _run_search(client, message, args[1].strip())
        return
    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🔎 <b>𝗠𝗘𝗗𝗜𝗔 𝗦𝗘𝗔𝗥𝗖𝗛</b>",
        DIV, "",
        "ᴄʜᴏᴏꜱᴇ ᴀ ᴍᴏᴅᴇ:",
    ])
    await message.reply_text(text, reply_markup=main_menu(),
                             parse_mode=ParseMode.HTML, disable_web_page_preview=True)


@Client.on_message(filters.text & filters.private & ~filters.command(["search", "s", "start", "index", "database"]))
async def handle_private_text(client: Client, message: Message):
    """Auto-search on any private text message."""
    if not message.text:
        return
    # Ignore messages from admins that aren't searches
    query = message.text.strip()
    if len(query) < 2 or len(query) > 120:
        return
    await _run_search(client, message, query)


# ═══════════════════════ CORE SEARCH ═══════════════════════
async def _run_search(client: Client, message: Message, raw_query: str):
    status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")

    norm, year, is_series = parse_query(raw_query)
    if not norm:
        try:
            await status.edit_text("❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
        except Exception:
            pass
        return

    mode = "series" if is_series else "movie"

    # Search indexed media across all shards
    if mode == "series":
        result = await engine.search_series(norm, year=year)
    else:
        # Search both in parallel to catch mixed results
        import asyncio as _a
        r_movie, r_series = await _a.gather(
            engine.search_movie(norm, year=year),
            engine.search_series(norm, year=year),
        )
        result = r_movie if r_movie.hits else r_series
        if r_movie.hits and r_series.hits:
            mode = "both"

    # Get metadata candidates (non-blocking — empty if provider down)
    meta = []
    try:
        meta = await metadata_provider.search(raw_query, year, is_series=(mode == "series"))
    except Exception:
        meta = []

    # Build candidate list: combine indexed availability + metadata
    candidates_list = _build_candidates(result.hits, meta, mode)

    if not candidates_list:
        # No results — show not-found
        if not result.complete:
            text = (
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ <b>ꜱᴇᴀʀᴄʜ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ</b>\n"
                f"{DIV}\n\n"
                "ᴏɴᴇ ᴏʀ ᴍᴏʀᴇ ᴍᴇᴅɪᴀ ᴅᴀᴛᴀʙᴀꜱᴇꜱ ᴄᴏᴜʟᴅ ɴᴏᴛ ʙᴇ ꜱᴇᴀʀᴄʜᴇᴅ.\n"
                "ᴘʟᴇᴀꜱᴇ ᴛʀʏ ᴀɢᴀɪɴ ɪɴ ᴀ ᴍᴏᴍᴇɴᴛ."
            )
            try:
                await status.edit_text(text, reply_markup=back_close("sr:back"),
                                       parse_mode=ParseMode.HTML)
            except Exception:
                pass
            return

        # Create a not-found request
        session = await sessions.create(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            query=raw_query,
            normalized_query=norm,
            mode=mode,
        )
        try:
            await request_repo.add(message.from_user.id, norm, raw_query, mode)
        except Exception:
            pass

        text = (
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            "❌ <b>ʀᴇꜱᴜʟᴛ ɴᴏᴛ ꜰᴏᴜɴᴅ</b>\n"
            f"{DIV}\n\n"
            f"🔎 Qᴜᴇʀʏ: <code>{raw_query}</code>\n\n"
            "ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ɪɴᴅᴇxᴇᴅ ꜰɪʟᴇ ɪꜱ ᴄᴜʀʀᴇɴᴛʟʏ ᴀᴠᴀɪʟᴀʙʟᴇ."
        )
        try:
            await status.edit_text(
                text,
                reply_markup=no_results(session.session_id if session else ""),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Save session with candidates
    session = await sessions.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=raw_query,
        normalized_query=norm,
        mode=mode,
        candidates=candidates_list,
    )
    if not session:
        try:
            await status.edit_text("❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ. ᴛʀʏ ᴀɢᴀɪɴ.")
        except Exception:
            pass
        return

    # Show candidates
    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🔎 <b>ꜱᴇᴀʀᴄʜ ʀᴇꜱᴜʟᴛꜱ</b>",
        DIV, "",
        f"🔍 Qᴜᴇʀʏ: <code>{raw_query}</code>",
        f"📦 Mᴀᴛᴄʜᴇꜱ: <code>{len(candidates_list)}</code>",
    ]
    if not result.complete:
        lines.append("⚠️ ꜱᴏᴍᴇ ꜱʜᴀʀᴅꜱ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ — ʀᴇꜱᴜʟᴛꜱ ᴍᴀʏ ʙᴇ ɪɴᴄᴏᴍᴘʟᴇᴛᴇ.")
    lines.extend(["", DIV, "", "ꜱᴇʟᴇᴄᴛ ᴀ ᴛɪᴛʟᴇ:"])

    try:
        await status.edit_text(
            "\n".join(lines),
            reply_markup=candidates(session.session_id, candidates_list),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[SEARCH] render failed: {e}")


def _build_candidates(hits: List[FileHit], meta: List[Dict[str, Any]],
                      mode: str) -> List[Dict[str, Any]]:
    """
    Merge indexed hits and metadata candidates into a unique list.
    Keyed by (normalized_title, year).
    """
    groups: Dict[str, Dict[str, Any]] = {}

    # From indexed hits
    for h in hits:
        key_title = h.normalized_series_title or h.normalized_title
        if not key_title:
            continue
        key = f"{key_title}|{h.year or ''}"
        entry = groups.setdefault(key, {
            "type": h.type,
            "title": h.series_title or h.title,
            "year": h.year,
            "poster": None,
            "rating": None,
            "languages": set(),
            "qualities": set(),
            "file_count": 0,
            "metadata_id": None,
            "metadata_source": None,
        })
        entry["file_count"] += 1
        entry["languages"].update(h.audio_languages or [])
        if h.quality:
            entry["qualities"].add(h.quality)

    # From metadata (adds posters/ratings and title suggestions)
    for m in meta:
        title = m.get("title", "")
        year = m.get("year")
        from media_search.normalizer import normalize
        key = f"{normalize(title)}|{year or ''}"
        entry = groups.get(key)
        if not entry:
            # Only add metadata-only candidates if we have any matching indexed title
            from media_search.normalizer import normalize as _n
            norm_title = _n(title)
            for k, v in groups.items():
                if v["title"] and _n(v["title"]) == norm_title:
                    entry = v
                    break
        if entry:
            entry["poster"] = entry.get("poster") or m.get("poster")
            entry["rating"] = entry.get("rating") or m.get("rating")
            entry["metadata_id"] = m.get("metadata_id")
            entry["metadata_source"] = m.get("metadata_source")

    out: List[Dict[str, Any]] = []
    for key, e in groups.items():
        e["languages"] = sorted(e["languages"])
        e["qualities"] = sorted(e["qualities"])
        out.append(e)

    # Sort: most files first
    out.sort(key=lambda x: x["file_count"], reverse=True)
    return out[:20]


# ═══════════════════════ MODE SELECTION ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:mode:(movie|series)$"))
async def cb_mode(client: Client, q: CallbackQuery):
    mode = q.matches[0].group(1)
    text = (
        f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
        f"🔎 <b>{'🎬 ᴍᴏᴠɪᴇ' if mode=='movie' else '📺 ꜱᴇʀɪᴇꜱ'} ꜱᴇᴀʀᴄʜ</b>\n"
        f"{DIV}\n\n"
        "ꜱᴇɴᴅ ᴛʜᴇ ᴛɪᴛʟᴇ ᴛᴏ ꜱᴇᴀʀᴄʜ.\n"
        "ᴇxᴀᴍᴘʟᴇ: <code>KGF</code> ᴏʀ <code>Breaking Bad</code>"
    )
    try:
        await q.message.edit_text(text, reply_markup=back_close("sr:back"),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sr:back$"))
async def cb_back(client: Client, q: CallbackQuery):
    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🔎 <b>𝗠𝗘𝗗𝗜𝗔 𝗦𝗘𝗔𝗥𝗖𝗛</b>",
        DIV, "",
        "ᴄʜᴏᴏꜱᴇ ᴀ ᴍᴏᴅᴇ:",
    ])
    try:
        await q.message.edit_text(text, reply_markup=main_menu(),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sr:close$"))
async def cb_close(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sr:refresh$"))
async def cb_refresh(client: Client, q: CallbackQuery):
    await cb_back(client, q)


# ═══════════════════════ TITLE SELECTION ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:pick:([a-f0-9]+):(\d+)$"))
async def cb_pick(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    if idx >= len(session.candidates):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    candidate = session.candidates[idx]
    await sessions.update(
        session_id,
        selected_title=candidate["title"],
        selected_normalized_title=candidate["title"].lower(),
        selected_year=candidate.get("year"),
    )
    await q.answer()

    # Fetch availability
    norm_title = candidate["title"].lower()
    if candidate["type"] == "series":
        avail = await engine.availability(norm_title)
        # Also try series-normalized
        avail2 = await engine.search_series(norm_title, limit=200)
        langs = sorted({l for h in avail2.hits for l in (h.audio_languages or [])})
    else:
        avail = await engine.availability(norm_title)
        langs = avail.get("languages", [])

    if not langs:
        await q.message.edit_text(
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"❌ ᴛʜɪꜱ ᴛɪᴛʟᴇ ʜᴀꜱ ɴᴏ ɪɴᴅᴇxᴇᴅ ꜰɪʟᴇꜱ ʏᴇᴛ.",
            reply_markup=back_close("sr:back"),
            parse_mode=ParseMode.HTML,
        )
        return

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"🎬 <b>{candidate['title']}</b>" + (f" ({candidate['year']})" if candidate.get('year') else ""),
        DIV, "",
        f"📦 Fɪʟᴇꜱ: <code>{avail.get('hit_count', 0)}</code>",
        "",
        "🌐 ꜱᴇʟᴇᴄᴛ ʟᴀɴɢᴜᴀɢᴇ:",
    ])
    try:
        await q.message.edit_text(text, reply_markup=languages(session_id, langs),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^sr:title_back:([a-f0-9]+)$"))
async def cb_title_back(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🔎 <b>ꜱᴇᴀʀᴄʜ ʀᴇꜱᴜʟᴛꜱ</b>",
        DIV, "",
        f"🔍 Qᴜᴇʀʏ: <code>{session.query}</code>",
        "",
        "ꜱᴇʟᴇᴄᴛ ᴀ ᴛɪᴛʟᴇ:",
    ]
    try:
        await q.message.edit_text(
            "\n".join(lines),
            reply_markup=candidates(session_id, session.candidates),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await q.answer()


# ═══════════════════════ LANGUAGE ═══════════════════════
@router_note = None  # placeholder to keep structure readable
@Client.on_callback_query(filters.regex(r"^sr:lang:([a-f0-9]+):(\d+)$"))
async def cb_lang(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    avail = await engine.availability(norm_title)
    langs = avail.get("languages", [])
    if idx >= len(langs):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    lang = langs[idx]
    await sessions.update(session_id, selected_language=lang)

    # Series → show seasons
    if session.mode == "series":
        seasons_list = avail.get("seasons", [])
        if not seasons_list:
            await q.answer("❌ ɴᴏ ꜱᴇᴀꜱᴏɴꜱ", show_alert=True)
            return
        text = "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"📺 <b>{session.selected_title}</b>",
            f"🌐 Lᴀɴɢᴜᴀɢᴇ: <code>{lang}</code>",
            DIV, "",
            "📚 ꜱᴇʟᴇᴄᴛ ꜱᴇᴀꜱᴏɴ:",
        ])
        try:
            await q.message.edit_text(text, reply_markup=seasons(session_id, seasons_list),
                                      parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await q.answer()
        return

    # Movie → show qualities
    quals = avail.get("qualities", [])
    if not quals:
        await q.answer("❌ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ", show_alert=True)
        return
    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"🎬 <b>{session.selected_title}</b>",
        f"🌐 Lᴀɴɢᴜᴀɢᴇ: <code>{lang}</code>",
        DIV, "",
        "🎞️ ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:",
    ])
    try:
        await q.message.edit_text(text, reply_markup=qualities(session_id, quals),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sr:lang_back:([a-f0-9]+)$"))
async def cb_lang_back(client: Client, q: CallbackQuery):
    await cb_title_back(client, q)


# ═══════════════════════ QUALITY ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:q:([a-f0-9]+):(\d+)$"))
async def cb_quality(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    avail = await engine.availability(norm_title)
    quals = avail.get("qualities", [])
    if idx >= len(quals):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    quality = quals[idx]
    await sessions.update(session_id, selected_quality=quality)

    # Retrieve matching files
    result = await engine.search_movie(norm_title)
    files = [h for h in result.hits if (h.quality or "").upper() == quality.upper()]
    if session.selected_language:
        files = [h for h in files if session.selected_language in (h.audio_languages or [])]
    files = ranker.rank(files)

    if not files:
        text = (
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"❌ <b>ɴᴏ {quality.upper()} ꜰɪʟᴇꜱ ᴀᴠᴀɪʟᴀʙʟᴇ</b>\n"
            f"{DIV}\n\n"
            "ɴᴏ ʀᴇʟᴇᴀꜱᴇ ᴡᴀꜱ ꜰᴏᴜɴᴅ ꜰᴏʀ ᴛʜɪꜱ ᴛɪᴛʟᴇ ɪɴ ᴛʜᴇ ꜱᴇʟᴇᴄᴛᴇᴅ ʟᴀɴɢᴜᴀɢᴇ."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 BACK TO QUALITY",
                                  callback_data=f"sr:q_back:{session_id}")],
            [InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")]])
        try:
            await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await q.answer()
        return

    # Render file list
    items = [
        {"size_human": _human_size(h.file_size), "codec": h.codec or "?"}
        for h in files[:SEARCH_PAGE_SIZE]
    ]
    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"🎬 <b>{session.selected_title}</b>",
        f"🌐 Lᴀɴɢᴜᴀɢᴇ: <code>{session.selected_language or '—'}</code>",
        f"🎞️ Qᴜᴀʟɪᴛʏ: <code>{quality}</code>",
        DIV, "",
        "📦 ᴀᴠᴀɪʟᴀʙʟᴇ ꜰɪʟᴇꜱ:",
    ])
    try:
        await q.message.edit_text(text, reply_markup=files_kb(session_id, items),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sr:q_back:([a-f0-9]+)$"))
async def cb_q_back(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    avail = await engine.availability(norm_title)
    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"🎬 <b>{session.selected_title}</b>",
        DIV, "",
        "🎞️ ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:",
    ])
    try:
        await q.message.edit_text(text, reply_markup=qualities(session_id, avail.get("qualities", [])),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


# ═══════════════════════ FILE DELIVERY ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:file:([a-f0-9]+):(\d+)$"))
async def cb_file(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    result = await engine.search_movie(norm_title)
    files = [h for h in result.hits
             if (h.quality or "").upper() == (session.selected_quality or "").upper()
             and (not session.selected_language
                  or session.selected_language in (h.audio_languages or []))]
    files = ranker.rank(files)
    if idx >= len(files):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    # Force-sub check
    ok, missing = await subscription.is_subscribed(client, q.from_user.id)
    if not ok:
        text = (
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            "⚠️ <b>ꜱᴜʙꜱᴄʀɪᴘᴛɪᴏɴ ʀᴇQᴜɪʀᴇᴅ</b>\n"
            f"{DIV}\n\n"
            "ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ."
        )
        try:
            await q.message.edit_text(text, reply_markup=sub_required(missing),
                                      parse_mode=ParseMode.HTML)
        except Exception:
            pass
        await q.answer()
        return

    await q.answer("📤 ꜱᴇɴᴅɪɴɢ...")
    hit = files[idx]
    group_id = q.message.chat.id if q.message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else None
    ok, err = await delivery.send_file(client, q.from_user.id, hit, group_id=group_id)
    if not ok and err:
        try:
            await q.message.reply_text(err)
        except Exception:
            pass


# ═══════════════════════ SERIES FLOW ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:seas:([a-f0-9]+):(\d+)$"))
async def cb_season(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    avail = await engine.availability(norm_title)
    seasons_list = avail.get("seasons", [])
    if idx >= len(seasons_list):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    season = seasons_list[idx]
    await sessions.update(session_id, selected_season=season)

    result = await engine.search_series(norm_title, season=season)
    eps = sorted({h.episode for h in result.hits if h.episode is not None})
    if not eps:
        await q.answer("❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)
        return

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"📺 <b>{session.selected_title}</b>",
        f"🎞️ Sᴇᴀꜱᴏɴ {season}",
        DIV, "",
        "📄 ꜱᴇʟᴇᴄᴛ ᴇᴘɪꜱᴏᴅᴇ:",
    ])
    try:
        await q.message.edit_text(text, reply_markup=episodes(session_id, eps),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sr:season_back:([a-f0-9]+)$"))
async def cb_season_back(client: Client, q: CallbackQuery):
    await cb_title_back(client, q)


@Client.on_callback_query(filters.regex(r"^sr:ep_page:([a-f0-9]+):(\d+)$"))
async def cb_ep_page(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    page = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    result = await engine.search_series(norm_title, season=session.selected_season)
    eps = sorted({h.episode for h in result.hits if h.episode is not None})
    try:
        await q.message.edit_reply_markup(episodes(session_id, eps, page=page))
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sr:ep:([a-f0-9]+):(\d+)$"))
async def cb_episode(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    ep_idx = int(q.matches[0].group(2))
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    norm_title = session.selected_title.lower() if session.selected_title else session.normalized_query
    result = await engine.search_series(norm_title, season=session.selected_season)
    eps = sorted({h.episode for h in result.hits if h.episode is not None})
    if ep_idx >= len(eps):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    episode = eps[ep_idx]
    await sessions.update(session_id, selected_episode=episode)

    ep_hits = [h for h in result.hits if h.episode == episode]
    if session.selected_language:
        ep_hits = [h for h in ep_hits if session.selected_language in (h.audio_languages or [])]
    if session.selected_quality:
        ep_hits = [h for h in ep_hits if (h.quality or "").upper() == session.selected_quality.upper()]

    if not ep_hits:
        await q.answer("❌ ɴᴏ ꜰɪʟᴇ", show_alert=True)
        return

    best = ranker.best_for_episode(ep_hits)
    others = [h for h in ranker.rank(ep_hits) if h is not best]

    # Build items list: best first
    items = []
    if best:
        items.append({"size_human": _human_size(best.file_size), "codec": best.codec or "?"})
    for h in others[:6]:
        items.append({"size_human": _human_size(h.file_size), "codec": h.codec or "?"})

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        f"📺 <b>{session.selected_title}</b>",
        f"🎞️ S{episode and session.selected_season:02d}E{episode:02d}",
        DIV, "",
        "📦 ᴀᴠᴀɪʟᴀʙʟᴇ ʀᴇʟᴇᴀꜱᴇꜱ:",
        "",
        "⭐ ʙᴇꜱᴛ ʀᴇʟᴇᴀꜱᴇ ꜱʜᴏᴡɴ ꜰɪʀꜱᴛ",
    ])
    try:
        await q.message.edit_text(text, reply_markup=files_kb(session_id, items),
                                  parse_mode=ParseMode.HTML)
    except Exception:
        pass
    await q.answer()


# ═══════════════════════ REQUEST + SUB CHECK ═══════════════════════
@Client.on_callback_query(filters.regex(r"^sr:request:([a-f0-9]+)$"))
async def cb_request(client: Client, q: CallbackQuery):
    session_id = q.matches[0].group(1)
    session = await sessions.get(session_id)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    ok = await request_repo.add(session.user_id, session.normalized_query,
                                session.query, session.mode)
    if ok:
        await q.answer("✅ ʀᴇǫᴜᴇꜱᴛ ꜱᴜʙᴍɪᴛᴛᴇᴅ", show_alert=True)
    else:
        await q.answer("ℹ️ ʀᴇǫᴜᴇꜱᴛ ᴀʟʀᴇᴀᴅʏ ᴘᴇɴᴅɪɴɢ", show_alert=True)


@Client.on_callback_query(filters.regex(r"^sr:check_sub$"))
async def cb_check_sub(client: Client, q: CallbackQuery):
    ok, missing = await subscription.is_subscribed(client, q.from_user.id)
    if ok:
        await q.answer("✅ ᴠᴇʀɪꜰɪᴇᴅ! ꜱᴇɴᴅ ʏᴏᴜʀ ꜱᴇᴀʀᴄʜ ᴀɢᴀɪɴ.", show_alert=True)
        try:
            await q.message.delete()
        except Exception:
            pass
    else:
        await q.answer("❌ ꜱᴛɪʟʟ ᴍɪꜱꜱɪɴɢ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)
