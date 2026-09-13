"""
🏨 DOWNTOWN VILLA — Auto-filter handlers.
PM search → title → language → quality → files → deliver to PM.
Filenames cleaned. Audio from file record ONLY (no IMDb enrichment).
"""
import asyncio
import logging
import re
from typing import Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from media_search.delivery import delivery
from media_search.engine import engine
from media_search.models import FileHit
from media_search.normalizer import normalize, parse_query
from media_search.ranker import ranker
from media_search.requests import requests as request_repo
from media_search.sessions import sessions
from media_search.subscription import subscription
from services.formatting import clean_filename, human_size_short

logger = logging.getLogger(__name__)

DIV = "━" * 26


# ═══════════════════════ HELPERS ═══════════════════════
def _display_title(t: str, year: Optional[int]) -> str:
    base = (t or "?").strip().title()
    return f"{base} ({year})" if year else base


def _strip_trailing_digits(s: str) -> str:
    return re.sub(r"\s+\d+\s*$", "", (s or "").strip()).strip()


async def _edit(target, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.warning(f"[SEARCH] edit failed: {type(e).__name__}: {e}")


def _sub_keyboard(missing: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for ch in missing[:5]:
        try:
            cid = str(ch).replace("-100", "").replace("-", "")
            url = f"https://t.me/c/{cid}/1"
        except Exception:
            url = "https://t.me/"
        rows.append([InlineKeyboardButton("📢 JOIN CHANNEL", url=url)])
    rows.append([InlineKeyboardButton("🔄 CHECK AGAIN", callback_data="sr:check_sub")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
    return InlineKeyboardMarkup(rows)


def _filter_by_title(hits, title, year):
    norm = normalize(title)
    out = []
    for h in hits:
        base = (h.series_title or h.title or "").strip()
        base_clean = _strip_trailing_digits(base)
        if normalize(base_clean) != norm:
            continue
        if year and h.year and h.year != year:
            continue
        out.append(h)
    if not out:
        for h in hits:
            if year and h.year and h.year != year:
                continue
            bn = normalize(h.series_title or h.title or "")
            if bn.startswith(norm) or norm.startswith(bn):
                out.append(h)
    return out


def _group_hits(hits):
    groups = {}
    for h in hits:
        base = (h.series_title or h.title or "?").strip()
        base_clean = _strip_trailing_digits(base) or base
        groups.setdefault((base_clean, h.year), []).append(h)
    return groups


def _dedupe_sorted_asc(hits: List[FileHit]) -> List[FileHit]:
    """Dedupe by file_unique_id, then sort ascending by size."""
    seen = set()
    uniq = []
    for h in hits:
        k = h.file_unique_id or h.file_id
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    uniq.sort(key=lambda h: (h.file_size is None, h.file_size or 0))
    return uniq


def _quality_summary(hits):
    order = ["2160P", "1440P", "1080P", "1080I", "720P", "576P", "480P", "360P"]
    quals = {(h.quality or "").upper() for h in hits if h.quality}
    return ", ".join([q for q in order if q in quals]) or "—"


def _codec_summary(hits):
    order = ["AV1", "HEVC", "H264", "VP9", "VP8", "MPEG4", "MPEG2"]
    codecs = {(h.codec or "").upper() for h in hits if h.codec}
    return ", ".join([c for c in order if c in codecs]) or "—"


def _audio_summary(hits):
    """Audio comes ONLY from file records."""
    langs = sorted({l for h in hits for l in (h.audio_languages or [])})
    return ", ".join(langs) if langs else "—"


def _subtitle_summary(hits):
    subs = sorted({s for h in hits for s in (h.subtitle_languages or [])})
    if subs:
        return ", ".join(subs)
    if any(h.has_subtitle for h in hits):
        return "YES"
    return "—"


# ═══════════════════════ MAIN ENTRY ═══════════════════════
async def _handle_search(client: Client, message: Message, raw_query: str,
                         is_group: bool = False, _depth: int = 0):
    logger.info(f"[SEARCH] START for {raw_query!r} depth={_depth}")

    try:
        status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
    except Exception as e:
        logger.exception(f"[SEARCH] reply failed: {e}")
        return

    norm, year, is_series = parse_query(raw_query)
    if not norm:
        await _edit(status, "❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
        return

    if is_series:
        result = await engine.search_series(norm, year=year)
    else:
        r_movie, r_series = await asyncio.gather(
            engine.search_movie(norm, year=year),
            engine.search_series(norm, year=year),
        )
        result = r_movie if r_movie.hits else r_series
        if not result.hits:
            result = await engine.search_any(norm, year=year)

    hits = result.hits
    logger.info(f"[SEARCH] {len(hits)} hits complete={result.complete}")

    if not hits:
        if not result.complete:
            await _edit(
                status,
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ ᴏɴᴇ ᴏʀ ᴍᴏʀᴇ ᴅᴀᴛᴀʙᴀꜱᴇꜱ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ. ᴛʀʏ ᴀɢᴀɪɴ.",
            )
            return
        await _handle_no_results(client, message, status, raw_query, norm, is_series)
        return

    groups = _group_hits(hits)
    candidates = [
        {"title": t, "year": y, "type": th[0].type, "count": len(th)}
        for (t, y), th in groups.items()
    ]

    session = await sessions.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=raw_query,
        normalized_query=norm,
        mode="series" if is_series else "movie",
        candidates=candidates,
    )
    if not session:
        await _edit(status, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ. ᴛʀʏ ᴀɢᴀɪɴ.")
        return

    sid = session.session_id

    if len(candidates) == 1:
        c = candidates[0]
        await sessions.update(sid, selected_title=c["title"], selected_year=c["year"])
        await _show_next_after_title(status, sid)
        return

    rows: List[List[InlineKeyboardButton]] = []
    for i, c in enumerate(candidates[:10]):
        label = _display_title(c["title"], c["year"])
        rows.append([InlineKeyboardButton(
            label.upper(), callback_data=f"sr:pick:{sid}:{i}",
        )])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        status,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🔎 <b>{len(candidates)} ᴛɪᴛʟᴇꜱ ꜰᴏᴜɴᴅ</b>",
            DIV, "",
            f"🔍 Qᴜᴇʀʏ: <code>{raw_query}</code>",
            "",
            "ꜱᴇʟᴇᴄᴛ ᴀ ᴛɪᴛʟᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ NO-RESULTS → IMDb ═══════════════════════
async def _handle_no_results(client, message, status, raw_query, norm, is_series):
    try:
        from media_search.spell_check import get_suggestions, clean_query
    except Exception as e:
        logger.warning(f"[SEARCH] spell_check unavailable: {e}")
        await _edit(status, f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{raw_query}</code>")
        return

    cleaned = clean_query(raw_query)
    suggestions: List[Dict] = []
    try:
        suggestions = await get_suggestions(cleaned, is_series=is_series)
    except Exception as e:
        logger.warning(f"[SEARCH] suggestions failed: {e}")

    if not suggestions and cleaned != raw_query:
        try:
            suggestions = await get_suggestions(raw_query, is_series=is_series)
        except Exception:
            pass

    if not suggestions:
        try:
            await request_repo.add(message.from_user.id, norm, raw_query,
                                   "series" if is_series else "movie")
        except Exception:
            pass
        await _edit(
            status,
            f"🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
            f"❌ ɴᴏ ᴍᴀᴛᴄʜɪɴɢ ꜰɪʟᴇ ꜰᴏʀ <code>{raw_query}</code>\n\n"
            f"📝 ʀᴇǫᴜᴇꜱᴛ ʀᴇᴄᴏʀᴅᴇᴅ.",
        )
        return

    session = await sessions.create(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=raw_query,
        normalized_query=norm,
        mode="series" if is_series else "movie",
        candidates=suggestions,
    )
    if not session:
        await _edit(status, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ. ᴛʀʏ ᴀɢᴀɪɴ.")
        return

    rows = []
    for i, s in enumerate(suggestions[:10]):
        title = s.get("title") or "?"
        yr = s.get("year")
        label = f"🎬 {title}" + (f" ({yr})" if yr else "")
        rows.append([InlineKeyboardButton(
            label.upper(),
            callback_data=f"spol:{session.session_id}:{i}",
        )])
    rows.append([InlineKeyboardButton(
        "🔍 CHECK ON GOOGLE",
        url=f"https://www.google.com/search?q={raw_query}",
    )])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        status,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            "🤔 <b>ᴅɪᴅ ʏᴏᴜ ᴍᴇᴀɴ?</b>",
            DIV, "",
            f"🔍 Yᴏᴜ ꜱᴇᴀʀᴄʜᴇᴅ: <code>{raw_query}</code>",
            f"📝 <b>{len(suggestions)}</b> ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ:",
            "",
            "ᴘɪᴄᴋ ᴛʜᴇ ᴏɴᴇ ʏᴏᴜ ᴍᴇᴀɴᴛ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


# ═══════════════════════ TITLE PICKER ═══════════════════════
async def _pick_title(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    if idx >= len(session.candidates):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    c = session.candidates[idx]
    await sessions.update(sid, selected_title=c["title"], selected_year=c["year"])
    await q.answer()
    await _show_next_after_title(q.message, sid)


# ═══════════════════════ SPOL (IMDb PICK) ═══════════════════════
async def _pick_suggestion(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    if idx >= len(session.candidates):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    s = session.candidates[idx]
    title = s.get("title") or ""
    year = s.get("year")
    imdb_id = s.get("metadata_id")
    await q.answer(f"🔎 ꜱᴇᴀʀᴄʜɪɴɢ: {title[:30]}")

    norm = normalize(title)
    result = await engine.search_any(norm, year=year)
    hits = _filter_by_title(result.hits, title, year)
    if not hits and year:
        result = await engine.search_any(norm, year=None)
        hits = _filter_by_title(result.hits, title, None)

    # ── Not found → request channel ──
    if not hits:
        try:
            from services.request_service import post_request
            await post_request(
                client=client,
                user_id=q.from_user.id,
                username=getattr(q.from_user, "username", "") or "",
                full_name=getattr(q.from_user, "first_name", "") or "",
                movie_name=title,
                imdb_id=imdb_id,
                user_query=session.query or title,
            )
        except Exception as e:
            logger.warning(f"[SEARCH] request post failed: {e}")

        try:
            await request_repo.add(
                q.from_user.id, norm, title,
                "series" if session.mode == "series" else "movie",
            )
        except Exception:
            pass

        admin_url = "https://t.me/"
        try:
            from core.config import OWNER_LNK, SUPPORT_CHAT
            admin_url = OWNER_LNK or SUPPORT_CHAT or admin_url
        except Exception:
            pass

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔰 REQUEST TO ADMIN", url=admin_url)],
            [InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")],
        ])
        try:
            year_txt = f" ({year})" if year else ""
            await q.message.edit_text(
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                f"😌 <b>{title}</b>{year_txt} ɪꜱ ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ.\n\n"
                "📝 ʀᴇǫᴜᴇꜱᴛ ꜱᴇɴᴛ — ᴀᴅᴍɪɴ ᴡɪʟʟ ɴᴏᴛɪꜰʏ ʏᴏᴜ ꜱᴏᴏɴ.",
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ── Found → continue ──
    await sessions.update(sid, selected_title=title, selected_year=year)
    try:
        await q.message.delete()
    except Exception:
        pass

    class _FakeMsg:
        def __init__(self, msg, from_user, chat):
            self._msg = msg
            self.from_user = from_user
            self.chat = chat
            self.text = title
            self.id = msg.id
        async def reply_text(self, *a, **kw):
            return await self._msg.reply_text(*a, **kw)

    fake = _FakeMsg(q.message, q.from_user, q.message.chat)
    try:
        status = await fake.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
    except Exception:
        return
    await _show_next_after_title(status, sid)


# ═══════════════════════ TITLE → LANG ═══════════════════════
async def _show_next_after_title(target, sid):
    session = await sessions.get(sid)
    if not session:
        return
    hits = await _search_for_session(session)
    if not hits:
        await _edit(target, "❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ᴛɪᴛʟᴇ.")
        return
    langs = sorted({l for h in hits for l in (h.audio_languages or [])})
    if not langs:
        await sessions.update(sid, selected_language="")
        await _show_qualities(target, sid)
        return
    await _show_languages(target, sid, langs)


# ═══════════════════════ LANGUAGE ═══════════════════════
async def _show_languages(target, sid, langs):
    session = await sessions.get(sid)
    if not session:
        return
    rows = []
    pair = []
    for i, lang in enumerate(langs[:12]):
        pair.append(InlineKeyboardButton(
            lang.upper(), callback_data=f"sr:lang:{sid}:{i}",
        ))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:back:{sid}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        target,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🎬 <b>{_display_title(session.selected_title, session.selected_year)}</b>",
            DIV, "",
            "🌐 ꜱᴇʟᴇᴄᴛ ʟᴀɴɢᴜᴀɢᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


async def _pick_lang(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _search_for_session(session)
    langs = sorted({l for h in hits for l in (h.audio_languages or [])})
    if idx >= len(langs):
        await q.answer("❌", show_alert=True); return
    lang = langs[idx]
    await sessions.update(sid, selected_language=lang)
    await q.answer()

    if session.mode == "series" or any(h.type == "series" for h in hits):
        seasons = sorted({h.season for h in hits
                          if h.season is not None and lang in (h.audio_languages or [])})
        if seasons:
            await _show_seasons(q.message, sid, seasons)
            return
    await _show_qualities(q.message, sid)


# ═══════════════════════ SEASONS ═══════════════════════
async def _show_seasons(target, sid, seasons_list):
    session = await sessions.get(sid)
    if not session:
        return
    rows = []
    pair = []
    for i, s in enumerate(seasons_list[:12]):
        pair.append(InlineKeyboardButton(
            f"SEASON {s:02d}", callback_data=f"sr:seas:{sid}:{i}",
        ))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:lang_back:{sid}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        target,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"📺 <b>{_display_title(session.selected_title, session.selected_year)}</b>",
            f"🌐 ʟᴀɴɢᴜᴀɢᴇ: <code>{session.selected_language or '—'}</code>",
            DIV, "",
            "📚 ꜱᴇʟᴇᴄᴛ ꜱᴇᴀꜱᴏɴ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


async def _pick_season(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _search_for_session(session)
    lang = session.selected_language
    seasons = sorted({h.season for h in hits
                      if h.season is not None and (not lang or lang in (h.audio_languages or []))})
    if idx >= len(seasons):
        await q.answer("❌", show_alert=True); return
    season = seasons[idx]
    await sessions.update(sid, selected_season=season)
    await q.answer()
    eps = sorted({h.episode for h in hits
                  if h.season == season and h.episode is not None
                  and (not lang or lang in (h.audio_languages or []))})
    if not eps:
        await q.answer("❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True); return
    await _show_episodes(q.message, sid, season, eps)


# ═══════════════════════ EPISODES ═══════════════════════
async def _show_episodes(target, sid, season, eps, page=0, per_page=20):
    session = await sessions.get(sid)
    if not session:
        return
    start = page * per_page
    slice_ = eps[start:start + per_page]

    rows = []
    trio = []
    for i, ep in enumerate(slice_):
        idx = start + i
        trio.append(InlineKeyboardButton(
            f"EP {ep:02d}", callback_data=f"sr:ep:{sid}:{idx}",
        ))
        if len(trio) == 3:
            rows.append(trio); trio = []
    if trio:
        rows.append(trio)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ PREV", callback_data=f"sr:ep_page:{sid}:{page-1}"))
    if start + per_page < len(eps):
        nav.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"sr:ep_page:{sid}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:seas_back:{sid}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    await _edit(
        target,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"📺 <b>{_display_title(session.selected_title, session.selected_year)}</b>",
            f"🎞️ Sᴇᴀꜱᴏɴ {season}",
            DIV, "",
            "📄 ꜱᴇʟᴇᴄᴛ ᴇᴘɪꜱᴏᴅᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


async def _pick_episode(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _search_for_session(session)
    lang = session.selected_language
    season = session.selected_season
    eps = sorted({h.episode for h in hits
                  if h.season == season and h.episode is not None
                  and (not lang or lang in (h.audio_languages or []))})
    if idx >= len(eps):
        await q.answer("❌", show_alert=True); return
    ep = eps[idx]
    await sessions.update(sid, selected_episode=ep)
    await q.answer()
    await _show_qualities(q.message, sid)


# ═══════════════════════ QUALITY ═══════════════════════
async def _show_qualities(target, sid):
    session = await sessions.get(sid)
    if not session:
        return
    hits = await _filter_hits(session)
    quals = sorted({(h.quality or "").upper() for h in hits if h.quality})
    if not quals:
        await _edit(target, "❌ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʟᴇᴄᴛɪᴏɴ.")
        return

    rows = []
    pair = []
    for i, qv in enumerate(quals[:10]):
        pair.append(InlineKeyboardButton(
            qv, callback_data=f"sr:q:{sid}:{i}",
        ))
        if len(pair) == 2:
            rows.append(pair); pair = []
    if pair:
        rows.append(pair)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:q_back:{sid}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    lines = ["🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"]
    lines.append(f"🎬 <b>{_display_title(session.selected_title, session.selected_year)}</b>")
    if session.selected_season and session.selected_episode:
        lines.append(f"🎞️ S{session.selected_season:02d}E{session.selected_episode:02d}")
    lines.append(f"🌐 ʟᴀɴɢᴜᴀɢᴇ: <code>{session.selected_language or '—'}</code>")
    lines.append(DIV)
    lines.append("")
    lines.append("🎞️ ꜱᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛʏ:")

    await _edit(target, "\n".join(lines), kb=InlineKeyboardMarkup(rows))


async def _pick_quality(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _filter_hits(session)
    quals = sorted({(h.quality or "").upper() for h in hits if h.quality})
    if idx >= len(quals):
        await q.answer("❌", show_alert=True); return
    qv = quals[idx]
    await sessions.update(sid, selected_quality=qv)
    await q.answer()
    await _show_files(q.message, sid)


# ═══════════════════════ FILES — CLEAN NAMES ═══════════════════════
async def _show_files(target, sid):
    session = await sessions.get(sid)
    if not session:
        return
    hits = await _filter_hits(session)
    uniq = _dedupe_sorted_asc(hits)
    if not uniq:
        await _edit(target, "❌ ɴᴏ ʀᴇʟᴇᴀꜱᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʟᴇᴄᴛɪᴏɴ.")
        return

    display = uniq[:10]

    # ── Clean button labels ──
    rows = []
    for i, h in enumerate(display):
        size = human_size_short(h.file_size)
        codec = (h.codec or "?").upper()
        clean = clean_filename(h.file_name, max_len=40)
        label = f"📦 {size} · {codec} · {clean}"
        if len(label) > 64:
            label = label[:61] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"sr:file:{sid}:{i}",
        )])

    if len(uniq) > 10:
        rows.append([InlineKeyboardButton(
            f"➕ {len(uniq) - 10} MORE",
            callback_data=f"sr:q_back:{sid}",
        )])

    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:q_back:{sid}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    # ── Header: audio comes from FILES only ──
    title = session.selected_title or "?"
    year = session.selected_year
    title_line = f"🎬 <b>{_display_title(title, year)}</b>"
    if session.selected_season and session.selected_episode:
        title_line = (
            f"📺 <b>{_display_title(title, year)}</b> · "
            f"<code>S{session.selected_season:02d}E{session.selected_episode:02d}</code>"
        )

    lines = [
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        DIV,
        "",
        title_line,
        "",
        f"🎞️ <b>Qᴜᴀʟɪᴛʏ</b> · <code>{_quality_summary(uniq)}</code>",
        f"🧬 <b>Cᴏᴅᴇᴄ</b> · <code>{_codec_summary(uniq)}</code>",
        f"🔊 <b>Aᴜᴅɪᴏ</b> · <code>{_audio_summary(uniq)}</code>",
        f"📝 <b>Sᴜʙᴛɪᴛʟᴇ</b> · <code>{_subtitle_summary(uniq)}</code>",
        "",
        DIV,
        "",
        f"📦 <b>{len(uniq)} ʀᴇʟᴇᴀꜱᴇꜱ</b> · ꜱᴍᴀʟʟ → ʙɪɢ",
        "",
        "ᴘɪᴄᴋ ᴀ ʀᴇʟᴇᴀꜱᴇ:",
    ]
    await _edit(target, "\n".join(lines), kb=InlineKeyboardMarkup(rows))


# ═══════════════════════ DELIVER FILE ═══════════════════════
async def _pick_file(client, q, sid, idx):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _filter_hits(session)
    uniq = _dedupe_sorted_asc(hits)
    if idx >= len(uniq):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True); return

    ok, missing = await subscription.is_subscribed(client, q.from_user.id)
    if not ok:
        await q.answer()
        try:
            await q.message.edit_text(
                "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
                "⚠️ ᴊᴏɪɴ ᴛʜᴇ ᴄʜᴀɴɴᴇʟꜱ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇ.",
                reply_markup=_sub_keyboard(missing),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    await q.answer("📤 ꜱᴇɴᴅɪɴɢ ᴛᴏ ʏᴏᴜʀ ᴘᴍ...")
    hit = uniq[idx]

    # Deliver to USER'S PM (never to the current chat)
    ok, err = await delivery.send_file(client, q.from_user.id, hit)
    if not ok and err:
        try:
            await q.message.reply_text(err)
        except Exception:
            pass


# ═══════════════════════ BACK NAVIGATION ═══════════════════════
async def _back_to_titles(client, q, sid):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    if len(session.candidates) == 1:
        await q.answer()
        await _show_next_after_title(q.message, sid)
        return
    rows = []
    for i, c in enumerate(session.candidates[:10]):
        label = _display_title(c["title"], c.get("year"))
        rows.append([InlineKeyboardButton(
            label.upper(), callback_data=f"sr:pick:{sid}:{i}",
        )])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
    await _edit(
        q.message,
        "\n".join([
            "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
            f"🔎 <b>{len(session.candidates)} ᴛɪᴛʟᴇꜱ</b>",
            DIV, "",
            "ꜱᴇʟᴇᴄᴛ ᴀ ᴛɪᴛʟᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )
    await q.answer()


async def _back_to_langs(client, q, sid):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    await q.answer()
    await _show_next_after_title(q.message, sid)


async def _back_to_quality(client, q, sid):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    await q.answer()
    await _show_qualities(q.message, sid)


async def _back_to_seasons(client, q, sid):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _search_for_session(session)
    lang = session.selected_language
    seasons = sorted({h.season for h in hits
                      if h.season is not None and (not lang or lang in (h.audio_languages or []))})
    if not seasons:
        await q.answer("❌ ɴᴏ ꜱᴇᴀꜱᴏɴꜱ", show_alert=True); return
    await q.answer()
    await _show_seasons(q.message, sid, seasons)


async def _episode_page(client, q, sid, page):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True); return
    hits = await _search_for_session(session)
    lang = session.selected_language
    season = session.selected_season
    eps = sorted({h.episode for h in hits
                  if h.season == season and h.episode is not None
                  and (not lang or lang in (h.audio_languages or []))})
    await q.answer()
    await _show_episodes(q.message, sid, season, eps, page=page)


# ═══════════════════════ INTERNAL ═══════════════════════
async def _search_for_session(session):
    norm = normalize(session.selected_title or session.normalized_query)
    result = await engine.search_any(norm, year=session.selected_year)
    return _filter_by_title(result.hits, session.selected_title or "", session.selected_year)


async def _filter_hits(session):
    hits = await _search_for_session(session)
    if session.selected_language:
        hits = [h for h in hits if session.selected_language in (h.audio_languages or [])]
    if session.selected_season is not None:
        hits = [h for h in hits if h.season == session.selected_season]
    if session.selected_episode is not None:
        hits = [h for h in hits if h.episode == session.selected_episode]
    if session.selected_quality:
        hits = [h for h in hits if (h.quality or "").upper() == session.selected_quality.upper()]
    return hits
