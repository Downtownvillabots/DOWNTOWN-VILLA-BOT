"""
Uppercase keyboards for search flow.
Every label must be CAPITALS per spec.
"""
from typing import List, Optional
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MOVIE SEARCH", callback_data="sr:mode:movie")],
        [InlineKeyboardButton("📺 SERIES SEARCH", callback_data="sr:mode:series")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sr:refresh")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")],
    ])


def back_close(back_cb: str = "sr:back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ BACK", callback_data=back_cb),
         InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")],
    ])


def candidates(session_id: str, items: List[dict], max_buttons: int = 8) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i, item in enumerate(items[:max_buttons]):
        title = item.get("title", "?")
        year = item.get("year")
        label = f"🎬 {title}" + (f" ({year})" if year else "")
        rows.append([
            InlineKeyboardButton(label.upper(), callback_data=f"sr:pick:{session_id}:{i}")
        ])
    rows.append([
        InlineKeyboardButton("🔄 RESET", callback_data="sr:back"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sr:close"),
    ])
    return InlineKeyboardMarkup(rows)


def languages(session_id: str, langs: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for i, lang in enumerate(langs[:12]):
        pair.append(
            InlineKeyboardButton(lang.upper(), callback_data=f"sr:lang:{session_id}:{i}")
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"sr:title_back:{session_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sr:close"),
    ])
    return InlineKeyboardMarkup(rows)


def qualities(session_id: str, quals: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for i, q in enumerate(quals[:10]):
        pair.append(InlineKeyboardButton(q.upper(), callback_data=f"sr:q:{session_id}:{i}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"sr:lang_back:{session_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sr:close"),
    ])
    return InlineKeyboardMarkup(rows)


def files(session_id: str, files: List[dict], max_btn: int = 8) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i, f in enumerate(files[:max_btn]):
        size = f.get("size_human", "?")
        codec = f.get("codec", "?")
        rows.append([
            InlineKeyboardButton(f"📦 {size} • {codec}".upper(),
                                 callback_data=f"sr:file:{session_id}:{i}")
        ])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"sr:q_back:{session_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sr:close"),
    ])
    return InlineKeyboardMarkup(rows)


def seasons(session_id: str, seasons: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for i, s in enumerate(seasons[:12]):
        pair.append(InlineKeyboardButton(f"SEASON {s:02d}",
                                          callback_data=f"sr:seas:{session_id}:{i}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"sr:title_back:{session_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sr:close"),
    ])
    return InlineKeyboardMarkup(rows)


def episodes(session_id: str, eps: List[int], page: int = 0,
             per_page: int = 20) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    start = page * per_page
    page_eps = eps[start:start + per_page]
    pair: List[InlineKeyboardButton] = []
    for i, ep in enumerate(page_eps):
        idx = start + i
        pair.append(InlineKeyboardButton(f"EP {ep:02d}",
                                          callback_data=f"sr:ep:{session_id}:{idx}"))
        if len(pair) == 3:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    nav: List[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ PREV", callback_data=f"sr:ep_page:{session_id}:{page-1}"))
    if start + per_page < len(eps):
        nav.append(InlineKeyboardButton("NEXT ▶️", callback_data=f"sr:ep_page:{session_id}:{page+1}"))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data=f"sr:season_back:{session_id}"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sr:close"),
    ])
    return InlineKeyboardMarkup(rows)


def sub_required(missing_channels: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for ch in missing_channels[:5]:
        # channel id is negative, strip -100
        try:
            cid = str(ch).replace("-100", "").replace("-", "")
            url = f"https://t.me/c/{cid}/1"
        except Exception:
            url = "https://t.me/"
        rows.append([InlineKeyboardButton(f"📢 JOIN CHANNEL", url=url)])
    rows.append([InlineKeyboardButton("🔄 CHECK AGAIN", callback_data="sr:check_sub")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")])
    return InlineKeyboardMarkup(rows)


def no_results(session_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 REQUEST", callback_data=f"sr:request:{session_id}")],
        [InlineKeyboardButton("🔎 NEW SEARCH", callback_data="sr:back")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="sr:close")],
    ])
