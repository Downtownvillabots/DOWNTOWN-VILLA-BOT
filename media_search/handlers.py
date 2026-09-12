"""
🏨 DOWNTOWN VILLA — Auto-filter handlers
Full interactive flow:
  Movie:  Title → Language → Quality → Release → Deliver
  Series: Title → Language → Season → Episode → Quality → Release → Deliver

Callbacks are registered in plugins/auto_filter.py (Pyrogram requires
top-level handlers), which delegates to the `_pick_*` functions here.
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

logger = logging.getLogger(__name__)

DIV = "━" * 26


# ═══════════════════════ HELPERS ═══════════════════════
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


def _display_title(t: str, year: Optional[int]) -> str:
    base = (t or "?").strip().title()
    return f"{base} ({year})" if year else base


def _strip_trailing_digits(s: str) -> str:
    return re.sub(r"\s+\d+\s*$", "", (s or "").strip()).strip()


async def _edit(target, text: str, kb: Optional[InlineKeyboardMarkup] = None):
    """Edit a Message or a CallbackQuery.message."""
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        msg_str = str(e).lower()
        if "not modified" in msg_str:
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


def _filter_by_title(hits: List[FileHit], title: str, year: Optional[int]) -> List[FileHit]:
    """Return only hits whose clean title matches the selected candidate."""
    norm = normalize(title)
    out: List[FileHit] = []
    for h in hits:
        base = (h.series_title or h.title or "").strip()
        base_clean = _strip_trailing_digits(base)
        if normalize(base_clean) != norm:
            continue
        if year and h.year and h.year != year:
            continue
        out.append(h)
    if not out:
        # Looser fallback
        for h in hits:
            if year and h.year and h.year != year:
                continue
            bn = normalize(h.series_title or h.title or "")
            if bn.startswith(norm) or norm.startswith(bn):
                out.append(h)
    return out


def _group_hits(hits: List[FileHit]) -> Dict[Tuple[str, Optional[int]], List[FileHit]]:
    groups: Dict[Tuple[str, Optional[int]], List[FileHit]] = {}
    for h in hits:
        base = (h.series_title or h.title or "?").strip()
        base_clean = _strip_trailing_digits(base) or base
        groups.setdefault((base_clean, h.year), []).append(h)
    return groups


# ═══════════════════════ MAIN ENTRY ═══════════════════════
async def _handle_search(client: Client, message: Message, raw_query: str,
                         is_group: bool = False):
    logger.info(f"[SEARCH] START for {raw_query!r} is_group={is_group}")

    try:
        status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
    except Exception as e:
        logger.exception(f"[SEARCH] reply failed: {e}")
        return

    norm, year, is_series = parse_query(raw_query)
    if not norm:
        await _edit(status, "❌ ᴘʟᴇᴀꜱᴇ ᴇɴᴛᴇʀ ᴀ ᴠᴀʟɪᴅ ꜱᴇᴀʀᴄʜ.")
        return

    # ── Search across all shards ──
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

        # ── SPELL CHECK ──
        await _handle_no_results(client, message, status, raw_query, norm, is_series)
        return

    # ── Group by (title, year) ──
    groups = _group_hits(hits)
    candidates = [
        {"title": t, "year": y, "type": th[0].type, "count": len(th)}
        for (t, y), th in groups.items()
    ]
    logger.info(f"[SEARCH] {len(candidates)} candidate(s)")

    # ── Save session ──
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

    # ── ONE candidate → jump straight to language ──
    if len(candidates) == 1:
        c = candidates[0]
        await sessions.update(sid, selected_title=c["title"], selected_year=c["year"])
        await _show_next_after_title(status, sid)
        return

    # ── MULTIPLE → title picker ──
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


# ═══════════════════════ CALLBACK IMPLEMENTATIONS ═══════════════════════
async def _pick_title(client: Client, q: CallbackQuery, sid: str, idx: int):
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


async def _show_next_after_title(target, sid: str):
    """After a title is picked, go to language (or skip to quality if no langs)."""
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


async def _show_languages(target, sid: str, langs: List[str]):
    session = await sessions.get(sid)
    if not session:
        return
    title = session.selected_title
    year = session.selected_year

    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
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
            f"🎬 <b>{_display_title(title, year)}</b>",
            DIV, "",
            "🌐 ꜱᴇʟᴇᴄᴛ ʟᴀɴɢᴜᴀɢᴇ:",
        ]),
        kb=InlineKeyboardMarkup(rows),
    )


async def _pick_lang(client: Client, q: CallbackQuery, sid: str, idx: int):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    hits = await _search_for_session(session)
    langs = sorted({l for h in hits for l in (h.audio_languages or [])})
    if idx >= len(langs):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    lang = langs[idx]
    await sessions.update(sid, selected_language=lang)
    await q.answer()

    # ── Series → seasons. Movie → qualities ──
    if session.mode == "series" or any(h.type == "series" for h in hits):
        seasons = sorted({h.season for h in hits
                          if h.season is not None and lang in (h.audio_languages or [])})
        if seasons:
            await _show_seasons(q.message, sid, seasons)
            return
    await _show_qualities(q.message, sid)


async def _show_seasons(target, sid: str, seasons_list: List[int]):
    session = await sessions.get(sid)
    if not session:
        return
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
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


async def _pick_season(client: Client, q: CallbackQuery, sid: str, idx: int):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    hits = await _search_for_session(session)
    lang = session.selected_language
    seasons = sorted({h.season for h in hits
                      if h.season is not None and (not lang or lang in (h.audio_languages or []))})
    if idx >= len(seasons):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    season = seasons[idx]
    await sessions.update(sid, selected_season=season)
    await q.answer()

    # Episodes for this season
    eps = sorted({h.episode for h in hits
                  if h.season == season and h.episode is not None
                  and (not lang or lang in (h.audio_languages or []))})
    if not eps:
        await q.answer("❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)
        return
    await _show_episodes(q.message, sid, season, eps)


async def _show_episodes(target, sid: str, season: int, eps: List[int], page: int = 0,
                         per_page: int = 20):
    session = await sessions.get(sid)
    if not session:
        return
    start = page * per_page
    slice_ = eps[start:start + per_page]

    rows: List[List[InlineKeyboardButton]] = []
    trio: List[InlineKeyboardButton] = []
    for i, ep in enumerate(slice_):
        idx = start + i
        trio.append(InlineKeyboardButton(
            f"EP {ep:02d}", callback_data=f"sr:ep:{sid}:{idx}",
        ))
        if len(trio) == 3:
            rows.append(trio); trio = []
    if trio:
        rows.append(trio)

    nav: List[InlineKeyboardButton] = []
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


async def _pick_episode(client: Client, q: CallbackQuery, sid: str, idx: int):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    hits = await _search_for_session(session)
    lang = session.selected_language
    season = session.selected_season
    eps = sorted({h.episode for h in hits
                  if h.season == season and h.episode is not None
                  and (not lang or lang in (h.audio_languages or []))})
    if idx >= len(eps):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    ep = eps[idx]
    await sessions.update(sid, selected_episode=ep)
    await q.answer()
    await _show_qualities(q.message, sid)


async def _show_qualities(target, sid: str):
    session = await sessions.get(sid)
    if not session:
        return
    hits = await _filter_hits(session)
    quals = sorted({(h.quality or "").upper() for h in hits if h.quality})
    if not quals:
        await _edit(target, "❌ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʟᴇᴄᴛɪᴏɴ.")
        return

    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
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


async def _pick_quality(client: Client, q: CallbackQuery, sid: str, idx: int):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    hits = await _filter_hits(session)
    quals = sorted({(h.quality or "").upper() for h in hits if h.quality})
    if idx >= len(quals):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return
    qv = quals[idx]
    await sessions.update(sid, selected_quality=qv)
    await q.answer()
    await _show_files(q.message, sid)


async def _show_files(target, sid: str):
    session = await sessions.get(sid)
    if not session:
        return
    hits = await _filter_hits(session)
    hits = ranker.rank(hits)

    # Dedupe
    seen = set()
    uniq: List[FileHit] = []
    for h in hits:
        k = h.file_unique_id or h.file_id
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)

    if not uniq:
        await _edit(target, "❌ ɴᴏ ʀᴇʟᴇᴀꜱᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇʟᴇᴄᴛɪᴏɴ.")
        return

    rows: List[List[InlineKeyboardButton]] = []
    for i, h in enumerate(uniq[:10]):
        codec = (h.codec or "?").upper()
        label = f"📦 {_human_size(h.file_size)} • {codec}"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"sr:file:{sid}:{i}",
        )])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"sr:q_back:{sid}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    lines = ["🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"]
    lines.append(f"🎬 <b>{_display_title(session.selected_title, session.selected_year)}</b>")
    if session.selected_season and session.selected_episode:
        lines.append(f"🎞️ S{session.selected_season:02d}E{session.selected_episode:02d}")
    lines.append(f"🌐 ʟᴀɴɢᴜᴀɢᴇ: <code>{session.selected_language or '—'}</code>")
    lines.append(f"🎞️ Qᴜᴀʟɪᴛʏ: <code>{session.selected_quality or '—'}</code>")
    lines.append(f"📦 ʀᴇʟᴇᴀꜱᴇꜱ: <code>{len(uniq)}</code>")
    lines.append(DIV)
    lines.append("")
    lines.append("ᴘɪᴄᴋ ᴀ ʀᴇʟᴇᴀꜱᴇ:")

    await _edit(target, "\n".join(lines), kb=InlineKeyboardMarkup(rows))


async def _pick_file(client: Client, q: CallbackQuery, sid: str, idx: int):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return

    hits = await _filter_hits(session)
    hits = ranker.rank(hits)
    seen = set()
    uniq: List[FileHit] = []
    for h in hits:
        k = h.file_unique_id or h.file_id
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    if idx >= len(uniq):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    # Force-sub
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

    await q.answer("📤 ꜱᴇɴᴅɪɴɢ...")
    hit = uniq[idx]
    ok, err = await delivery.send_file(client, q.from_user.id, hit)
    if not ok and err:
        try:
            await q.message.reply_text(err)
        except Exception:
            pass


# ── Back navigation ──
async def _back_to_titles(client: Client, q: CallbackQuery, sid: str):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    if len(session.candidates) == 1:
        await q.answer()
        await _show_next_after_title(q.message, sid)
        return
    rows: List[List[InlineKeyboardButton]] = []
    for i, c in enumerate(session.candidates[:10]):
        label = _display_title(c["title"], c["year"])
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


async def _back_to_langs(client: Client, q: CallbackQuery, sid: str):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    await q.answer()
    await _show_next_after_title(q.message, sid)


async def _back_to_quality(client: Client, q: CallbackQuery, sid: str):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    await q.answer()
    await _show_qualities(q.message, sid)


async def _back_to_seasons(client: Client, q: CallbackQuery, sid: str):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    hits = await _search_for_session(session)
    lang = session.selected_language
    seasons = sorted({h.season for h in hits
                      if h.season is not None and (not lang or lang in (h.audio_languages or []))})
    if not seasons:
        await q.answer("❌ ɴᴏ ꜱᴇᴀꜱᴏɴꜱ", show_alert=True)
        return
    await q.answer()
    await _show_seasons(q.message, sid, seasons)


async def _episode_page(client: Client, q: CallbackQuery, sid: str, page: int):
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    hits = await _search_for_session(session)
    lang = session.selected_language
    season = session.selected_season
    eps = sorted({h.episode for h in hits
                  if h.season == season and h.episode is not None
                  and (not lang or lang in (h.audio_languages or []))})
    await q.answer()
    await _show_episodes(q.message, sid, season, eps, page=page)


# ═══════════════════════ INTERNAL SEARCH ═══════════════════════
async def _search_for_session(session) -> List[FileHit]:
    norm = normalize(session.selected_title or session.normalized_query)
    result = await engine.search_any(norm, year=session.selected_year)
    return _filter_by_title(result.hits, session.selected_title or "", session.selected_year)


async def _filter_hits(session) -> List[FileHit]:
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
# ═══════════════════════ NO-RESULTS + SPELL CHECK FLOW ═══════════════════════
async def _handle_no_results(client: Client, message: Message, status,
                             raw_query: str, norm: str, is_series: bool):
    """Triggered when a search returns zero hits. Runs spell-check flow."""
    from core.config import SPELL_CHECK_REPLY
    from media_search.spell_check import ai_spell_check, get_suggestions, clean_query

    # ── Stage 1: auto-correct (only if enabled) ──
    if SPELL_CHECK_REPLY:
        await _edit(status, "🤖 ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ, ᴀɪ ɪꜱ ᴄʜᴇᴄᴋɪɴɢ ʏᴏᴜʀ ꜱᴘᴇʟʟɪɴɢ...")
        corrected = None
        try:
            corrected = await ai_spell_check(raw_query, is_series=is_series)
        except Exception as e:
            logger.warning(f"[SEARCH] ai_spell_check failed: {e}")

        if corrected and normalize(corrected) != norm:
            await _edit(
                status,
                f"✅ ᴀɪ ꜱᴜɢɢᴇꜱᴛᴇᴅ: <code>{corrected}</code>\n"
                f"🔍 ꜱᴇᴀʀᴄʜɪɴɢ ꜰᴏʀ ɪᴛ...",
            )
            await asyncio.sleep(0.6)
            # Recursive retry with corrected title
            try:
                await status.delete()
            except Exception:
                pass
            return await _handle_search(client, message, corrected, is_group=False)

    # ── Stage 2: manual picker ──
    cleaned = clean_query(raw_query)
    suggestions: List[Dict] = []
    try:
        suggestions = await get_suggestions(cleaned, is_series=is_series)
    except Exception as e:
        logger.warning(f"[SEARCH] suggestion fetch failed: {e}")

    if not suggestions:
        # Nothing to suggest — log request + friendly message
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

    # Save suggestion session
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

    # Build picker buttons
    rows: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(suggestions[:10]):
        title = s.get("title") or "?"
        year = s.get("year")
        label = f"🎬 {title}" + (f" ({year})" if year else "")
        rows.append([InlineKeyboardButton(
            label.upper(),
            callback_data=f"spol:{session.session_id}:{i}",
        )])
    rows.append([InlineKeyboardButton("🔍 CHECK ON GOOGLE",
                                      url=f"https://www.google.com/search?q={raw_query}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])

    text = "\n".join([
        "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>",
        "🤔 <b>ᴅɪᴅ ʏᴏᴜ ᴍᴇᴀɴ?</b>",
        DIV, "",
        f"🔍 Yᴏᴜ ꜱᴇᴀʀᴄʜᴇᴅ: <code>{raw_query}</code>",
        f"📝 ᴡᴇ ꜰᴏᴜɴᴅ <b>{len(suggestions)}</b> ᴘᴏꜱꜱɪʙʟᴇ ᴛɪᴛʟᴇꜱ:",
        "",
        "ᴘɪᴄᴋ ᴛʜᴇ ᴏɴᴇ ʏᴏᴜ ᴍᴇᴀɴᴛ:",
    ])
    await _edit(status, text, kb=InlineKeyboardMarkup(rows))


# ═══════════════════════ SPOL CALLBACK IMPLEMENTATION ═══════════════════════
async def _pick_suggestion(client: Client, q: CallbackQuery, sid: str, idx: int):
    """Called from auto_filter.py's spol callback."""
    session = await sessions.get(sid)
    if not session or session.user_id != q.from_user.id:
        await q.answer("⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        return
    if idx >= len(session.candidates):
        await q.answer("❌ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        return

    s = session.candidates[idx]
    title = s.get("title") or ""
    await q.answer("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")

    # Re-run the search with the suggested title
    try:
        await q.message.delete()
    except Exception:
        pass
    # Reuse the original user's message context: build a fake call
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
    await _handle_search(client, fake, title, is_group=False)
