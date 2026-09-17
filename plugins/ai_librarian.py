# plugins/ai_librarian.py
"""
🎛️ AI LIBRARIAN v4 — uses SERIES GROUP engine (same quality detection)

Features:
- Same engine + parser as plugins/series_group.py
- Sees ALL qualities (480p/720p/1080p/etc.)
- Episode × quality grid with 🟢/🟡/🔴 status
- Per-series quality prefs
- Auto-scan, manual scan, mark complete
- Delete individual files
"""
import asyncio
import logging
import os
import random
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from database import db_manager

try:
    from core.config import ADMINS as _ADMINS
    ADMINS = list(_ADMINS or [])
except Exception:
    ADMINS = []

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

SESSION_TTL = 900
DAILY_REPORT_HOUR = 9
SERIES_PER_AUTO = 3
PROGRESS_UPDATE_INTERVAL = 2.0

DIV = "━" * 26
DIV2 = "─" * 26

# Priority order of qualities (highest first)
QUALITY_ORDER = ["4320P", "2160P", "1440P", "1080P", "720P", "576P", "480P", "360P"]

QUALITY_RANK = {
    "4320P": 100, "8K": 100, "2160P": 90, "4K": 90, "UHD": 90,
    "1440P": 80, "2K": 80, "1080P": 70, "FULLHD": 70, "FHD": 70,
    "720P": 60, "HD": 60, "576P": 50, "480P": 40, "SD": 40,
    "360P": 30, "240P": 20, "CAM": 5, "HDCAM": 5, "TS": 3,
    "TELESYNC": 3, "UNKNOWN": 25,
}

_M_BOLD = {
    **{chr(ord('A') + i): "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[i] for i in range(26)},
    **{chr(ord('a') + i): "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[i] for i in range(26)},
    **{chr(ord('0') + i): "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[i] for i in range(10)},
}
_M_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
}
def fb(s): return "".join(_M_BOLD.get(c, c) for c in str(s))
def sc(s): return "".join(_M_SC.get(c, c) for c in str(s))


def _fmt_int(n) -> str:
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return "0"

def _fmt_size(b) -> str:
    if not b: return "0 B"
    try: s = float(b)
    except (TypeError, ValueError): return "0 B"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if s < 1024: return f"{s:.2f} {u}"
        s /= 1024
    return f"{s:.2f} PB"

def _esc(t) -> str:
    if t is None: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception: return False

def _now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y · %H:%M IST")


# ═══════════════════════════════════════════════════════════════════════════
# DB
# ═══════════════════════════════════════════════════════════════════════════
def _get_db():
    try:
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                d = fn()
                if d is not None: return d
    except Exception: pass
    try: return db_manager._db
    except Exception: return None

def _completed_coll():
    d = _get_db(); return d["ai_completed"] if d is not None else None
def _settings_coll():
    d = _get_db(); return d["ai_settings"] if d is not None else None
def _prefs_coll():
    d = _get_db(); return d["ai_prefs"] if d is not None else None


async def _get_setting(key, default=None):
    c = _settings_coll()
    if c is None: return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception: return default

async def _set_setting(key, value):
    c = _settings_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {key: value, "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _is_completed(slug):
    c = _completed_coll()
    if c is None: return False
    try: return (await c.find_one({"title_slug": slug})) is not None
    except Exception: return False

async def _mark_completed(title, slug, count):
    c = _completed_coll()
    if c is None: return False
    try:
        await c.update_one({"title_slug": slug},
            {"$set": {"title": title, "title_slug": slug,
                      "total_files": count, "completed_at": time.time()}},
            upsert=True)
        return True
    except Exception: return False

async def _unmark_completed(slug):
    c = _completed_coll()
    if c is None: return False
    try: return (await c.delete_one({"title_slug": slug})).deleted_count > 0
    except Exception: return False

async def _list_completed(limit=100):
    c = _completed_coll()
    if c is None: return []
    try: return await c.find({}).sort("completed_at", -1).limit(limit).to_list(limit)
    except Exception: return []

async def _count_completed():
    c = _completed_coll()
    if c is None: return 0
    try: return await c.count_documents({})
    except Exception: return 0


async def _delete_file_record(file_id):
    """Delete by file_id across all media shards."""
    if not file_id: return False
    try:
        from database import db_registry
        deleted = False
        for entry in db_registry.media_entries():
            try:
                r = await entry.db["media_files"].delete_one({"file_id": file_id})
                if r.deleted_count > 0:
                    deleted = True; continue
                r = await entry.db["media_files"].delete_one(
                    {"file_unique_id": file_id})
                if r.deleted_count > 0: deleted = True
            except Exception:
                continue
        return deleted
    except Exception as e:
        logger.warning(f"[AI] delete_file: {e}")
        return False


# ─── Series quality prefs ───
async def _get_prefs(slug):
    c = _prefs_coll()
    if c is None: return []
    try:
        doc = await c.find_one({"title_slug": slug})
        return list(doc.get("keep_qualities") or []) if doc else []
    except Exception: return []

async def _set_prefs(slug, title, quals):
    c = _prefs_coll()
    if c is None: return False
    try:
        await c.update_one({"title_slug": slug},
            {"$set": {"title_slug": slug, "title": title,
                      "keep_qualities": list(quals),
                      "updated_at": time.time()}},
            upsert=True)
        return True
    except Exception: return False

async def _list_prefs():
    c = _prefs_coll()
    if c is None: return []
    try: return await c.find({}).sort("updated_at", -1).to_list(200)
    except Exception: return []


# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}

def _new_session(uid, action, **data):
    _SESSIONS[uid] = {"action": action, "data": data,
                      "expires": time.time() + SESSION_TTL}

def _get_session(uid):
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(uid, None); return None
    return s

def _clear_session(uid): _SESSIONS.pop(uid, None)

def _cleanup_sessions():
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now: _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# ⭐⭐ SAME ENGINE AS SERIES GROUP ⭐⭐
# ═══════════════════════════════════════════════════════════════════════════
async def _engine_search(title, season=None, language=None, quality=None):
    """EXACTLY the same as series_group._engine_search"""
    try:
        from media_search.engine import engine
        from media_search.normalizer import normalize
    except Exception as e:
        logger.exception(f"[AI] engine import failed: {e}")
        return []

    all_files = []
    try:
        norm = normalize(title)
        result = await engine.search_series(norm)
        hits = result.hits
        if not hits:
            result = await engine.search_any(norm)
            hits = result.hits

        logger.info(f"[AI] engine: {len(hits)} hits for {norm!r}")

        for h in hits:
            h_season = getattr(h, "season", None)
            h_episode = getattr(h, "episode", None)
            h_quality = getattr(h, "quality", None)
            h_langs = list(getattr(h, "audio_languages", []) or [])
            file_name = getattr(h, "file_name", "") or ""

            if h_season is None or h_episode is None or not h_quality or not h_langs:
                p = _parse_filename_light(file_name)
                if h_season is None: h_season = p.get("season")
                if h_episode is None: h_episode = p.get("episode")
                if not h_quality: h_quality = p.get("quality")
                if not h_langs: h_langs = p.get("languages") or []

            if season is not None and h_season != season: continue
            if language:
                ll = language.lower()
                hl = [l.lower() for l in h_langs]
                if hl and not any(ll in l or l in ll for l in hl): continue
            if quality and h_quality:
                if h_quality.upper() != quality.upper(): continue

            all_files.append({
                "file_hit": h,
                "file_id": getattr(h, "file_id", "") or "",
                "file_unique_id": getattr(h, "file_unique_id", None),
                "file_name": file_name,
                "file_size": getattr(h, "file_size", 0) or 0,
                "season": h_season,
                "episode": h_episode,
                "quality": (h_quality or "UNKNOWN").upper(),
                "languages": h_langs,
                "title": getattr(h, "title", "") or "",
                "series_title": getattr(h, "series_title", None) or "",
                "chat_id": getattr(h, "chat_id", None),
                "message_id": getattr(h, "message_id", None) or
                              getattr(h, "msg_id", None),
            })
    except Exception as e:
        logger.exception(f"[AI] engine search failed: {e}")

    return _dedupe_by_episode(all_files)


# ═══════════════════════════════════════════════════════════════════════════
# SAME LIGHT PARSER AS SERIES GROUP
# ═══════════════════════════════════════════════════════════════════════════
_SE_PATTERNS = [
    re.compile(r"[sS](\d{1,2})[\s._-]?[eE][pP]?(\d{1,3})"),
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?[eE]pisode[\s._-]?(\d{1,3})"),
    re.compile(r"[sS](\d{1,2})[\s._-]+[eE](\d{1,3})"),
]
_SEASON_ONLY = [
    re.compile(r"\b[sS](\d{1,2})\b(?![\s._-]?[eE])"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})\b(?![\s._-]?[eE])"),
]
_QUALITY_MARKERS = [
    ("4320p", "4320P"), ("2160p", "2160P"), ("4k", "4K"), ("uhd", "UHD"),
    ("1440p", "1440P"), ("1080p", "1080P"), ("fullhd", "1080P"), ("fhd", "1080P"),
    ("720p", "720P"), ("576p", "576P"), ("480p", "480P"), ("360p", "360P"),
]
_LANG_ALIASES = {
    "English": ["english", "eng"], "Hindi": ["hindi", "hin"],
    "Tamil": ["tamil", "tam"], "Telugu": ["telugu", "tel"],
    "Malayalam": ["malayalam", "mal"], "Kannada": ["kannada", "kan"],
    "Bengali": ["bengali", "bangla"], "Marathi": ["marathi"],
    "Punjabi": ["punjabi"], "Korean": ["korean"], "Japanese": ["japanese"],
    "Chinese": ["chinese", "mandarin"], "Spanish": ["spanish"],
    "French": ["french"], "German": ["german"], "Italian": ["italian"],
    "Portuguese": ["portuguese"], "Russian": ["russian"], "Turkish": ["turkish"],
    "Arabic": ["arabic"], "Thai": ["thai"],
}


def _parse_filename_light(filename):
    out = {"season": None, "episode": None, "quality": None, "languages": []}
    if not filename: return out
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts)$", "", name, flags=re.I)
    wl = name.lower()

    for pat in _SE_PATTERNS:
        m = pat.search(name)
        if m:
            try:
                out["season"] = int(m.group(1))
                out["episode"] = int(m.group(2)); break
            except Exception: continue
    if out["season"] is None:
        for pat in _SEASON_ONLY:
            m = pat.search(name)
            if m:
                try: out["season"] = int(m.group(1)); break
                except Exception: continue

    for marker, label in _QUALITY_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", wl):
            out["quality"] = label; break

    langs = []
    for ln, aliases in _LANG_ALIASES.items():
        for a in aliases:
            if re.search(r"\b" + re.escape(a) + r"\b", wl):
                if ln not in langs: langs.append(ln)
                break
    out["languages"] = langs
    return out


def _dedupe_by_episode(files):
    """Same as series group — 1 file per (season, episode, quality)."""
    if not files: return []
    seen_ids: Set[str] = set()
    by_id = []
    for f in files:
        fid = str(f.get("file_id") or f.get("file_unique_id") or "")
        if fid and fid in seen_ids: continue
        if fid: seen_ids.add(fid)
        by_id.append(f)

    def _size(f):
        s = f.get("file_size") or 0
        try: return int(s)
        except (TypeError, ValueError): return 0

    by_id.sort(key=_size, reverse=True)

    seen_keys: Set[Tuple] = set()
    out = []
    for f in by_id:
        s = f.get("season"); e = f.get("episode")
        if e is None:
            p = _parse_filename_light(f.get("file_name") or "")
            if p.get("episode") is not None:
                e = p["episode"]; f["episode"] = e
            if p.get("season") is not None and s is None:
                s = p["season"]; f["season"] = s
        q = (f.get("quality") or "UNKNOWN").upper().strip()
        key = (s, e, q)
        if key in seen_keys: continue
        seen_keys.add(key)
        out.append(f)

    out.sort(key=lambda x: (
        x.get("season") or 0,
        x.get("episode") if x.get("episode") is not None else 9999))
    return out


# ═══════════════════════════════════════════════════════════════════════════
# CATALOG BUILD (uses engine results)
# ═══════════════════════════════════════════════════════════════════════════
class SeriesCatalog:
    """Groups files by: title → season → episode → quality."""
    def __init__(self):
        # {title_slug: {"title": str, "seasons": {s: {ep: {q: file}}}}}
        self.data: Dict[str, Dict[str, Any]] = {}

    def add_file(self, f: Dict[str, Any]) -> bool:
        title = (f.get("series_title") or f.get("title") or "").strip()
        if not title: return False
        season = f.get("season")
        episode = f.get("episode")
        if season is None: return False
        quality = (f.get("quality") or "UNKNOWN").upper()
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if not slug: return False

        if slug not in self.data:
            self.data[slug] = {
                "title": title,
                "seasons": defaultdict(lambda: defaultdict(dict)),
                "file_count": 0,
            }

        self.data[slug]["seasons"][season][episode][quality] = f
        self.data[slug]["file_count"] += 1
        return True

    def list_series(self) -> List[Dict[str, Any]]:
        out = [{"title_slug": k, "title": v["title"],
                "file_count": v["file_count"],
                "season_count": len(v["seasons"])} for k, v in self.data.items()]
        out.sort(key=lambda x: x["title"].lower())
        return out


def _summarize_catalog(cat: SeriesCatalog, slug: str) -> Dict[str, Any]:
    """Return overall qualities, seasons, episodes count."""
    series = cat.data.get(slug) or {}
    seasons = series.get("seasons") or {}
    qualities: Set[str] = set()
    all_eps: Set[Tuple[int, Optional[int]]] = set()
    for sn, eps in seasons.items():
        for ep, qmap in eps.items():
            all_eps.add((sn, ep))
            for q in qmap.keys():
                qualities.add(q)
    return {
        "qualities": sorted(qualities, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True),
        "season_count": len(seasons),
        "episode_count": len(all_eps),
        "file_count": series.get("file_count", 0),
    }


# ═══════════════════════════════════════════════════════════════════════════
# TMDB SUGGEST (for manual scan)
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_suggest(query):
    if not TMDB_API_KEY: return []
    try:
        import aiohttp
    except ImportError: return []
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "en-US"}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get("https://api.themoviedb.org/3/search/tv",
                                params=params, timeout=12) as r:
                if r.status != 200: return []
                data = await r.json()
    except Exception: return []

    out = []
    for it in (data.get("results") or [])[:8]:
        t = it.get("name") or it.get("original_name") or ""
        if not t: continue
        date = it.get("first_air_date") or ""
        out.append({
            "title": t, "year": (date or "")[:4],
            "tmdb_id": it.get("id"),
            "rating": it.get("vote_average", 0),
        })
    return out


def kb_tmdb_suggest(items):
    rows = [[InlineKeyboardButton(
        f"🎬 {(it.get('title') or '?')[:38]}"
        + (f" ({it['year']})" if it.get("year") else ""),
        callback_data=f"ai:pick_tmdb:{i}")]
        for i, it in enumerate(items)]
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_main(auto_on, completed, total):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 AUTO MODE ON" if auto_on else "🔴 AUTO MODE OFF",
                              callback_data="ai:toggle_auto")],
        [InlineKeyboardButton("🚀 AUTO SCAN", callback_data="ai:auto"),
         InlineKeyboardButton("✍️ MANUAL SCAN", callback_data="ai:manual")],
        [InlineKeyboardButton(f"📚 ALL SERIES ({total})", callback_data="ai:all"),
         InlineKeyboardButton(f"✅ COMPLETED ({completed})", callback_data="ai:completed")],
        [InlineKeyboardButton("🎯 QUALITY PREFS", callback_data="ai:prefs"),
         InlineKeyboardButton("📊 STATUS", callback_data="ai:last_report")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="ai:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
    ])


def kb_series_result(slug, i, t):
    rows = [
        [InlineKeyboardButton("📊 QUALITY GRID",
                              callback_data=f"ai:grid:{slug}")],
        [InlineKeyboardButton("📋 EPISODE LIST",
                              callback_data=f"ai:eps:{slug}")],
        [InlineKeyboardButton("🎯 SET KEEP QUALITIES",
                              callback_data=f"ai:pref:{slug}")],
        [InlineKeyboardButton("✅ MARK COMPLETE",
                              callback_data=f"ai:complete:{slug}")],
    ]
    if i < t:
        rows.append([InlineKeyboardButton(f"⏭️ NEXT ({i+1}/{t})",
                                           callback_data=f"ai:next:{slug}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_series_list(lst):
    rows = []
    for s in lst[:25]:
        title = (s.get("title") or "?")[:32]
        count = s.get("file_count", 0)
        rows.append([InlineKeyboardButton(
            f"🎬 {title} · {count}",
            callback_data=f"ai:view:{s['title_slug']}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_episode_files(slug, season, episode, quality, files):
    rows = []
    for i, f in enumerate(files[:10]):
        q = f.get("quality", "?")
        langs = "+".join(f.get("languages", [])) or "?"
        ep_i = episode if episode is not None else 0
        rows.append([InlineKeyboardButton(f"🗑️ {i+1}. {q} · {langs}",
            callback_data=f"ai:del_pick:{slug}:{season}:{ep_i}:{q}:{i}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"ai:grid:{slug}"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_delete(slug, season, episode, quality, idx):
    ep_i = episode if episode is not None else 0
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, DELETE",
            callback_data=f"ai:del_go:{slug}:{season}:{ep_i}:{quality}:{idx}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"ai:grid:{slug}")]])


def kb_quality_picker(slug, avail, cur):
    rows = []; row = []
    for q in avail:
        mark = "✅" if q in cur else "⬜"
        row.append(InlineKeyboardButton(f"{mark} {q}",
            callback_data=f"ai:pref_tog:{slug}:{q}"))
        if len(row) == 3: rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("💾 SAVE", callback_data=f"ai:pref_save:{slug}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"ai:view:{slug}"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_back(t="ai:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=t),
        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")]])


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_main():
    auto_on = await _get_setting("auto_mode", True)
    comp = await _count_completed()
    total = await _get_setting("total_series", 0)
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎛️ <b>{fb('AI LIBRARIAN')}</b>",
        DIV, "",
        f"⚙️ {sc('auto mode')} · {'🟢 ᴏɴ' if auto_on else '🔴 ᴏꜰꜰ'}",
        f"✅ {sc('completed')} · <code>{_fmt_int(comp)}</code>",
        f"📚 {sc('total series')} · <code>{_fmt_int(total)}</code>",
        "", DIV2, "",
        f"🚀 {sc('auto')} · 3 ꜱᴇʀɪᴇꜱ ꜰʀᴏᴍ ᴅʙ",
        f"✍️ {sc('manual')} · ᴛᴍᴅʙ ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ",
        "", DIV2,
        f"🕒 <code>{_now_ist()}</code>",
    ]), kb_main(auto_on, comp, total)


def _progress_bar(p, w=16):
    p = max(0.0, min(100.0, float(p)))
    filled = int(w * p / 100); empty = w - filled
    block = "🟩" if p >= 75 else ("🟨" if p >= 50 else ("🟧" if p >= 25 else "🟥"))
    return block * filled + "⬛" * empty + f"  {p:.0f}%"


def _view_scanning(cur, total):
    p = (cur / total * 100) if total else 0
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('SCANNING')}</b>",
        DIV, "",
        f"<code>{_progress_bar(p)}</code>",
        "",
        f"📁 <code>{_fmt_int(cur)}</code> / <code>{_fmt_int(total)}</code>",
    ])


def _view_series_overview(series: Dict[str, Any], prefs: List[str],
                          i: int, t: int) -> str:
    """Overview with quality × episode status."""
    title = series.get("title") or "?"
    seasons = series.get("seasons") or {}

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>",
        f"📄 {sc('series')} · <code>{i}/{t}</code>",
        DIV, "",
    ]

    total_files = 0
    complete_eps = 0
    partial_eps = 0
    missing_eps = 0

    for sn in sorted(seasons.keys()):
        eps = seasons[sn]
        lines.append(f"📺 <b>{sc('Season')} {sn:02d}</b> · "
                     f"<code>{len(eps)} ᴇᴘɪꜱᴏᴅᴇꜱ</code>")

        # Quality map for this season
        qual_set: Set[str] = set()
        for ep, qmap in eps.items():
            for q in qmap.keys():
                qual_set.add(q)
            total_files += len(qmap)
        qual_list = sorted(qual_set, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True)

        # Per-episode status
        for ep in sorted(eps.keys(), key=lambda e: (e is None, e or 0)):
            qmap = eps[ep]
            ep_label = f"E{ep:02d}" if ep is not None else "?"

            have = sorted(qmap.keys(),
                           key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
            # Any admin prefs filter
            if prefs:
                keep = [q for q in have if q in prefs]
                ignore = [q for q in have if q not in prefs]
                if keep:
                    icon = "🟢"
                    complete_eps += 1
                elif ignore:
                    icon = "🟡"
                    partial_eps += 1
                else:
                    icon = "🔴"
                    missing_eps += 1
                q_str = " ".join(f"{'✅' if q in prefs else '⏭️'}{q}" for q in have)
            else:
                if len(have) >= 2:
                    icon = "🟢"; complete_eps += 1
                elif have:
                    icon = "🟡"; partial_eps += 1
                else:
                    icon = "🔴"; missing_eps += 1
                q_str = " ".join(f"✅{q}" for q in have)

            lines.append(f"   {icon} <b>{ep_label}</b> · {q_str}")

        # Quality summary line
        lines.append(f"   📊 {sc('qualities')} · <code>{', '.join(qual_list) or '—'}</code>")
        lines.append("")

    lines.append(DIV2)
    lines.append(f"📁 {sc('total files')} · <code>{_fmt_int(total_files)}</code>")
    lines.append(f"🟢 {sc('complete')} · <code>{complete_eps}</code>   "
                 f"🟡 {sc('partial')} · <code>{partial_eps}</code>   "
                 f"🔴 {sc('missing')} · <code>{missing_eps}</code>")
    if prefs:
        lines.append(f"🎯 {sc('keeping')} · <code>{', '.join(prefs)}</code>")
    else:
        lines.append(f"🎯 {sc('keeping')} · ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇꜱ")
    return "\n".join(lines)


def _view_quality_grid(series: Dict[str, Any], prefs: List[str]) -> str:
    """Matrix view: episodes × qualities with ✅/❌"""
    title = series.get("title") or "?"
    seasons = series.get("seasons") or {}

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{_esc(title)}</b> · {sc('Quality Grid')}",
        DIV, "",
    ]

    for sn in sorted(seasons.keys()):
        eps = seasons[sn]
        qual_set: Set[str] = set()
        for qmap in eps.values():
            qual_set.update(qmap.keys())
        qual_list = sorted(qual_set, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True)
        if not qual_list:
            lines.append(f"📺 <b>{sc('Season')} {sn:02d}</b> · —")
            continue

        # Header: short quality labels
        header = "       " + "  ".join(f"{q[:5]:>5}" for q in qual_list)
        lines.append(f"📺 <b>{sc('Season')} {sn:02d}</b>")
        lines.append(f"<code>{header}</code>")

        for ep in sorted(eps.keys(), key=lambda e: (e is None, e or 0)):
            qmap = eps[ep]
            ep_label = f"E{ep:02d}" if ep is not None else "?"
            row = " ".join(
                f"{'  ✅ ' if q in qmap else '  ❌ '}" for q in qual_list
            )
            lines.append(f"<code>{ep_label:>4}  {row}</code>")
        lines.append("")

    lines.append(DIV2)
    lines.append(f"✅ = {sc('available')}  ·  ❌ = {sc('missing')}")
    return "\n".join(lines)


def _view_episode_quality_picker(series: Dict[str, Any], season: int,
                                  episode: Optional[int],
                                  qmap: Dict[str, Dict[str, Any]],
                                  prefs: List[str]) -> str:
    ep_label = f"S{season:02d}" + (f"E{episode:02d}" if episode else "")
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(series.get('title'))}</b> · <code>{ep_label}</code>",
        DIV, "",
        f"📁 <code>{len(qmap)}</code> ǫᴜᴀʟɪᴛɪᴇꜱ ꜰᴏᴜɴᴅ",
        "",
    ]
    for q in sorted(qmap.keys(), key=lambda x: QUALITY_RANK.get(x, 0),
                     reverse=True):
        f = qmap[q]
        langs = "+".join(f.get("languages", [])) or "?"
        size = _fmt_size(f.get("file_size", 0))
        tag = ""
        if prefs and q not in prefs:
            tag = " · 🗑️ ᴛᴏ ʀᴇᴍᴏᴠᴇ"
        lines.append(f"🎯 <code>{q}</code> · 🌍 <code>{langs}</code> · 📦 {size}{tag}")
    lines += ["", DIV2, f"📌 {sc('tap below to manage a quality')}"]
    return "\n".join(lines)


async def _safe_edit(t, text, kb=None):
    try:
        m = getattr(t, "message", t)
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                           disable_web_page_preview=True)
        return True
    except MessageNotModified: return True
    except Exception as e:
        logger.exception(f"[AI] edit: {e}"); return False


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.command(["ai", "librarian", "ailib"]) & filters.private, group=-430)
async def cmd_ai(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        _clear_session(message.from_user.id)
        text, kb = await _view_main()
        await message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[AI] /ai: {e}")


@Client.on_message(filters.command(["aidb", "aishards"]) & filters.private, group=-430)
async def cmd_aidb(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        from database import db_registry
        lines = ["🗄️ <b>AI ᴅɪᴀɢɴᴏꜱᴛɪᴄꜱ</b>",
                 "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                 f"📁 <b>{len(db_registry.media_entries())} ᴍᴇᴅɪᴀ ꜱʜᴀʀᴅꜱ</b>", ""]
        for entry in db_registry.media_entries():
            try:
                n = await entry.db["media_files"].estimated_document_count()
            except Exception: n = -1
            lines.append(f"• <code>DB{entry.index + 1}</code> · {_fmt_int(n)}")
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[AI] aidb: {e}")
        await message.reply_text(f"❌ {_esc(e)}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:main$"), group=-430)
async def cb_main(client, q):
    try:
        text, kb = await _view_main()
        await _safe_edit(q, text, kb); await q.answer()
    except Exception as e: logger.exception(f"[AI] cb_main: {e}")


@Client.on_callback_query(filters.regex(r"^ai:close$"), group=-430)
async def cb_close(client, q):
    try:
        _clear_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        try: await q.answer("ᴄʟᴏꜱᴇᴅ")
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:toggle_auto$"), group=-430)
async def cb_toggle(client, q):
    cur = await _get_setting("auto_mode", True)
    await _set_setting("auto_mode", not cur)
    await q.answer("🟢 ᴀᴜᴛᴏ ᴏɴ" if not cur else "🔴 ᴀᴜᴛᴏ ᴏꜰꜰ")
    text, kb = await _view_main()
    await _safe_edit(q, text, kb)


# ═══════════════════════════════════════════════════════════════════════════
# SCAN — uses engine (same as series group)
# ═══════════════════════════════════════════════════════════════════════════
async def _build_catalog_from_titles(titles: List[str]) -> SeriesCatalog:
    """Take a list of titles, run engine search on each, build catalog."""
    cat = SeriesCatalog()
    for title in titles:
        try:
            files = await _engine_search(title)
            for f in files:
                cat.add_file(f)
        except Exception as e:
            logger.warning(f"[AI] scan '{title}': {e}")
    return cat


async def _discover_all_series() -> List[str]:
    """Discover all series titles by scanning shards + parsing filenames."""
    titles: Set[str] = set()
    try:
        from database import db_registry
        for entry in db_registry.media_entries():
            try:
                # Sample unique normalized_series_title
                pipeline = [
                    {"$match": {"type": "series",
                                 "normalized_series_title": {"$exists": True,
                                                              "$ne": None}}},
                    {"$group": {"_id": "$normalized_series_title"}},
                    {"$limit": 500},
                ]
                async for doc in entry.db["media_files"].aggregate(pipeline):
                    t = doc.get("_id")
                    if t: titles.add(t)
            except Exception: pass
    except Exception as e:
        logger.warning(f"[AI] discover: {e}")
    return sorted(titles)


# ═══════════════════════════════════════════════════════════════════════════
# AUTO SCAN
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:auto$"), group=-430)
async def cb_auto(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        await q.answer("🚀 ꜱᴄᴀɴɴɪɴɢ...")
        try:
            status = await q.message.edit_text(_view_scanning(0, 0),
                                                parse_mode=ParseMode.HTML)
        except Exception: status = q.message

        # Discover series titles
        titles = await _discover_all_series()
        logger.info(f"[AI] discovered {len(titles)} unique series")

        # Update progress
        try:
            await client.edit_message_text(
                chat_id=q.message.chat.id, message_id=status.id,
                text=_view_scanning(len(titles), len(titles)),
                parse_mode=ParseMode.HTML)
        except Exception: pass

        # Build catalog using engine
        cat = await _build_catalog_from_titles(titles)
        await _set_setting("total_series", len(cat.data))

        # Filter pending
        pending: List[Dict[str, Any]] = []
        for s in cat.list_series():
            if not await _is_completed(s["title_slug"]):
                pending.append(s)

        if not pending:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=status.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"✅ <b>{fb('ALL REVIEWED')}</b>",
                        DIV, "",
                        f"🎉 {sc('every series is marked complete')}",
                        f"📊 {sc('total')} · <code>{len(cat.data)}</code>",
                    ]),
                    reply_markup=kb_back("ai:main"),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        random.shuffle(pending)
        picked = pending[:SERIES_PER_AUTO]

        _new_session(q.from_user.id, "auto_scan",
                     picked=[s["title_slug"] for s in picked], index=0)
        sess = _SESSIONS[q.from_user.id]
        sess["catalog_data"] = cat.data
        sess["current_total"] = len(picked)

        await _show_series(client, q.message.chat.id, status.id,
                            picked[0]["title_slug"], 1, len(picked))
    except Exception as e:
        logger.exception(f"[AI] auto: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# MANUAL SCAN — TMDB suggest
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:manual$"), group=-430)
async def cb_manual(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    _new_session(q.from_user.id, "manual_name")
    await _safe_edit(q, "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✍️ <b>{fb('MANUAL SCAN')}</b>", DIV, "",
        f"📝 {sc('send a name or short form')}", "",
        f"📌 {sc('examples')}: <code>got</code> · <code>breaking bad</code>",
        "", f"💡 {sc('bot suggests from tmdb')}",
    ]), InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")]]))
    await q.answer()


@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=-429)
async def ai_manual_input(client, message):
    if not message.from_user: return
    s = _get_session(message.from_user.id)
    if not s or s["action"] != "manual_name":
        return
    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()
    if len(text) < 2:
        return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")

    _clear_session(message.from_user.id)

    try:
        loading = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ ᴛᴍᴅʙ...")
    except Exception: return

    suggestions = await _tmdb_suggest(text)

    if not suggestions:
        # No TMDB → direct engine scan
        try:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=loading.id,
                text="🔍 ᴛᴍᴅʙ ɴᴏ ʀᴇꜱᴜʟᴛ · ꜱᴄᴀɴɴɪɴɢ ᴅʙ...",
                parse_mode=ParseMode.HTML)
        except Exception: pass

        files = await _engine_search(text)
        if not files:
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"❌ <b>{fb('NOT FOUND')}</b>", DIV, "",
                        f"🔍 <code>{_esc(text)}</code>",
                        f"📌 {sc('not in your db')}",
                    ]),
                    reply_markup=kb_back("ai:main"),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        cat = SeriesCatalog()
        for f in files:
            cat.add_file(f)
        if not cat.data:
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text="⚠️ ɴᴏ ꜱᴇʀɪᴇꜱ ꜰᴏᴜɴᴅ ɪɴ ᴅʙ.",
                    reply_markup=kb_back("ai:main"),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        _new_session(message.from_user.id, "manual_result")
        sess = _SESSIONS[message.from_user.id]
        sess["catalog_data"] = cat.data
        slug0 = list(cat.data.keys())[0]
        await _show_series(client, message.chat.id, loading.id, slug0, 1, 1)
        return

    _new_session(message.from_user.id, "manual_tmdb_pick", suggestions=suggestions)

    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🔎 <b>{fb('TMDB SUGGESTIONS')}</b>", DIV, "",
             f"📝 <code>{_esc(text)}</code>", "",
             f"📌 {sc('tap a title to scan')}", "", DIV2, ""]
    for i, it in enumerate(suggestions, 1):
        t = it.get("title") or "?"
        yr = it.get("year") or ""
        r = it.get("rating", 0)
        lines.append(f"<b>{i}.</b> <b>{_esc(t)}</b> ({yr}) · ⭐ {r:.1f}")

    try:
        await client.edit_message_text(
            chat_id=message.chat.id, message_id=loading.id,
            text="\n".join(lines),
            reply_markup=kb_tmdb_suggest(suggestions),
            parse_mode=ParseMode.HTML)
    except Exception as e: logger.warning(f"[AI] suggest: {e}")


@Client.on_callback_query(filters.regex(r"^ai:pick_tmdb:(\d+)$"), group=-430)
async def cb_pick_tmdb(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s or s["action"] != "manual_tmdb_pick":
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        sugg = (s.get("data") or {}).get("suggestions") or []
        if idx < 0 or idx >= len(sugg):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen = sugg[idx]
        title = chosen.get("title") or ""
        _clear_session(q.from_user.id)

        await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ...")
        try:
            await q.message.edit_text(_view_scanning(0, 0),
                                       parse_mode=ParseMode.HTML)
        except Exception: pass

        # ⭐ USE ENGINE
        files = await _engine_search(title)
        if not files:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=q.message.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"❌ <b>{fb('NOT IN YOUR DB')}</b>", DIV, "",
                        f"🎬 <b>{_esc(title)}</b>",
                        "", DIV2, "",
                        f"📌 {sc('not in your library')}",
                    ]),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✍️ SEARCH AGAIN",
                                               callback_data="ai:manual")],
                        [InlineKeyboardButton("◀️ MAIN", callback_data="ai:main"),
                         InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
                    ]),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        cat = SeriesCatalog()
        for f in files:
            cat.add_file(f)
        if not cat.data:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=q.message.id,
                    text="⚠️ ɴᴏ ꜱᴇʀɪᴇꜱ ꜰᴏᴜɴᴅ.",
                    reply_markup=kb_back("ai:main"),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        _new_session(q.from_user.id, "manual_result")
        sess = _SESSIONS[q.from_user.id]
        sess["catalog_data"] = cat.data

        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        best_slug = None
        for k in cat.data.keys():
            if slug in k or k in slug:
                best_slug = k; break
        if not best_slug:
            best_slug = list(cat.data.keys())[0]

        await _show_series(client, q.message.chat.id, q.message.id,
                            best_slug, 1, 1)
    except Exception as e:
        logger.exception(f"[AI] pick_tmdb: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# SHOW SERIES
# ═══════════════════════════════════════════════════════════════════════════
async def _show_series(client, chat_id, msg_id, slug, i, t):
    sess = None
    for uid, s in _SESSIONS.items():
        if "catalog_data" in s:
            sess = s; break
    if not sess or not sess.get("catalog_data"):
        try:
            await client.edit_message_text(chat_id=chat_id, message_id=msg_id,
                text="⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ.", parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    series = sess["catalog_data"].get(slug)
    if not series:
        try:
            await client.edit_message_text(chat_id=chat_id, message_id=msg_id,
                text="⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ.", parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    prefs = await _get_prefs(slug)
    text = _view_series_overview(series, prefs, i, t)
    kb = kb_series_result(slug, i, t)

    sess["current_slug"] = slug
    sess["current_index"] = i
    sess["current_total"] = t

    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except MessageNotModified: pass
    except Exception as e: logger.debug(f"[AI] show_series: {e}")


@Client.on_callback_query(filters.regex(r"^ai:next:([a-z0-9_]+)$"), group=-430)
async def cb_next(client, q):
    try:
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        d = s.get("data") or {}
        picked = d.get("picked") or []
        i = d.get("index", 0) + 1
        if i >= len(picked): return await q.answer("✅ ᴀʟʟ ᴅᴏɴᴇ", show_alert=True)
        s["data"]["index"] = i
        await q.answer()
        await _show_series(client, q.message.chat.id, q.message.id,
                            picked[i], i + 1, len(picked))
    except Exception as e: logger.exception(f"[AI] next: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ⭐ QUALITY GRID ⭐
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:grid:([a-z0-9_]+)$"), group=-430)
async def cb_grid(client, q):
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        prefs = await _get_prefs(slug)
        text = _view_quality_grid(series, prefs)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ BACK", callback_data=f"ai:view:{slug}"),
             InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
        ])
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] grid: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# ⭐ EPISODE LIST (drill-down) ⭐
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:eps:([a-z0-9_]+)$"), group=-430)
async def cb_eps(client, q):
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        seasons = series.get("seasons") or {}
        if not seasons:
            return await q.answer("⚠️ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)

        # Show episode picker as buttons — one per episode (S..E..)
        rows = []
        for sn in sorted(seasons.keys()):
            eps = seasons[sn]
            for ep in sorted(eps.keys(), key=lambda e: (e is None, e or 0)):
                qmap = eps[ep]
                ep_label = f"S{sn:02d}E{ep:02d}" if ep is not None else f"S{sn:02d}"
                # Status icon
                if len(qmap) >= 2:
                    icon = "🟢"
                elif qmap:
                    icon = "🟡"
                else:
                    icon = "🔴"
                rows.append([InlineKeyboardButton(
                    f"{icon} {ep_label} · {len(qmap)} ǫᴜᴀʟ",
                    callback_data=f"ai:epq:{slug}:{sn}:"
                                   f"{ep if ep is not None else 0}")])
        rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"ai:view:{slug}"),
                     InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])

        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📋 <b>{_esc(series.get('title'))}</b>",
            DIV, "",
            f"📌 {sc('tap an episode to view its qualities')}",
            "",
            f"🟢 = 2+ ǫᴜᴀʟɪᴛɪᴇꜱ · 🟡 = 1 ǫᴜᴀʟɪᴛʏ",
        ]
        await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] eps: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(
    filters.regex(r"^ai:epq:([a-z0-9_]+):(\d+):(\d+)$"), group=-430)
async def cb_epq(client, q):
    """Show per-episode quality picker with delete buttons."""
    try:
        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        ep_raw = int(q.matches[0].group(3))
        episode = ep_raw if ep_raw > 0 else None
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        eps = (series.get("seasons") or {}).get(season, {})
        qmap = eps.get(episode, {})
        if not qmap:
            return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ᴇᴘɪꜱᴏᴅᴇ",
                                    show_alert=True)

        prefs = await _get_prefs(slug)
        text = _view_episode_quality_picker(series, season, episode, qmap, prefs)

        # One button per quality to delete
        rows = []
        qs_sorted = sorted(qmap.keys(),
                            key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
        for i, q_key in enumerate(qs_sorted):
            rows.append([InlineKeyboardButton(
                f"🗑️ DELETE {q_key}",
                callback_data=f"ai:del_pick:{slug}:{season}:"
                               f"{episode if episode is not None else 0}:"
                               f"{q_key}:{i}")])
        rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"ai:eps:{slug}"),
                     InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])

        await _safe_edit(q, text, InlineKeyboardMarkup(rows))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] epq: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# VIEW FILES (backwards-compat — jumps to grid)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:view:([a-z0-9_]+)$"), group=-430)
async def cb_view(client, q):
    """Jump to quality grid."""
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        prefs = await _get_prefs(slug)
        text = _view_series_overview(series, prefs,
                                      s.get("current_index", 1),
                                      s.get("current_total", 1))
        kb = kb_series_result(slug, s.get("current_index", 1),
                                s.get("current_total", 1))
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e: logger.exception(f"[AI] view: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# PREFS / COMPLETE / DELETE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:pref:([a-z0-9_]+)$"), group=-430)
async def cb_pref(client, q):
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        avail = set()
        for _, eps in (series.get("seasons") or {}).items():
            for _, qmap in eps.items():
                for q_key in qmap.keys():
                    avail.add(q_key)
        al = sorted(avail, key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
        if not al: return await q.answer("⚠️ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ", show_alert=True)
        cur = await _get_prefs(slug)
        s["pref_working"] = list(cur)
        await _safe_edit(q,
            _view_quality_picker(series.get("title"), al, cur),
            kb_quality_picker(slug, al, cur))
        await q.answer()
    except Exception as e: logger.exception(f"[AI] pref: {e}")


def _view_quality_picker(title, avail, cur):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('QUALITY PREFS')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>", "",
        f"📊 {sc('found')} · <code>{', '.join(avail) or 'none'}</code>",
        f"✅ {sc('keeping')} · <code>{', '.join(cur) or 'none'}</code>",
    ])


@Client.on_callback_query(filters.regex(r"^ai:pref_tog:([a-z0-9_]+):(\w+)$"), group=-430)
async def cb_pref_tog(client, q):
    try:
        slug = q.matches[0].group(1); qual = q.matches[0].group(2)
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        w = s.get("pref_working") or []
        if qual in w: w.remove(qual)
        else: w.append(qual)
        s["pref_working"] = w
        series = (s.get("catalog_data") or {}).get(slug) or {}
        avail = set()
        for _, eps in (series.get("seasons") or {}).items():
            for _, qmap in eps.items():
                for q_key in qmap.keys():
                    avail.add(q_key)
        al = sorted(avail, key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
        await _safe_edit(q, _view_quality_picker(series.get("title"), al, w),
                          kb_quality_picker(slug, al, w))
        await q.answer("✅" if qual in w else "⬜")
    except Exception as e: logger.exception(f"[AI] pref_tog: {e}")


@Client.on_callback_query(filters.regex(r"^ai:pref_save:([a-z0-9_]+)$"), group=-430)
async def cb_pref_save(client, q):
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        w = s.get("pref_working") or []
        series = (s.get("catalog_data") or {}).get(slug) or {}
        title = series.get("title") or slug
        ok = await _set_prefs(slug, title, w)
        await q.answer("✅ ꜱᴀᴠᴇᴅ" if ok else "❌ ꜰᴀɪʟᴇᴅ")
        if not ok: return
        await _show_series(client, q.message.chat.id, q.message.id, slug,
                            s.get("current_index", 1),
                            s.get("current_total", 1))
    except Exception as e: logger.exception(f"[AI] pref_save: {e}")


@Client.on_callback_query(filters.regex(r"^ai:prefs$"), group=-430)
async def cb_prefs(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        items = await _list_prefs()
        lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                 f"🎯 <b>{fb('QUALITY PREFS')}</b>", DIV, ""]
        if not items: lines.append("⚪ ɴᴏɴᴇ ꜱᴇᴛ.")
        else:
            for it in items[:30]:
                lines.append(f"🎬 <b>{_esc(it.get('title'))}</b>")
                lines.append(f"   ✅ <code>{', '.join(it.get('keep_qualities') or [])}</code>")
                lines.append("")
        await _safe_edit(q, "\n".join(lines), kb_back("ai:main"))
        await q.answer()
    except Exception as e: logger.exception(f"[AI] prefs: {e}")


@Client.on_callback_query(filters.regex(r"^ai:complete:([a-z0-9_]+)$"), group=-430)
async def cb_complete(client, q):
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = (s.get("catalog_data") or {}).get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        ok = await _mark_completed(series.get("title", slug), slug,
                                     series.get("file_count", 0))
        if not ok: return await q.answer("❌ ꜰᴀɪʟᴇᴅ", show_alert=True)
        await q.answer("✅ ᴍᴀʀᴋᴇᴅ")
        await _safe_edit(q, "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{fb('MARKED COMPLETE')}</b>", DIV, "",
            f"🎬 <b>{_esc(series.get('title'))}</b>",
            f"📁 <code>{_fmt_int(series.get('file_count', 0))}</code> ꜰɪʟᴇꜱ",
            f"📅 <code>{_now_ist()}</code>",
        ]), InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ NEXT", callback_data=f"ai:next:{slug}")],
            [InlineKeyboardButton("◀️ MAIN", callback_data="ai:main"),
             InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")]]))
    except Exception as e: logger.exception(f"[AI] complete: {e}")


@Client.on_callback_query(filters.regex(r"^ai:all$"), group=-430)
async def cb_all(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")
        try:
            status = await q.message.edit_text(_view_scanning(0, 0),
                                                parse_mode=ParseMode.HTML)
        except Exception: status = q.message

        titles = await _discover_all_series()
        cat = await _build_catalog_from_titles(titles)
        await _set_setting("total_series", len(cat.data))

        all_s = cat.list_series()
        if not all_s:
            try:
                await client.edit_message_text(chat_id=q.message.chat.id,
                    message_id=status.id, text="⚪ ɴᴏ ꜱᴇʀɪᴇꜱ ꜰᴏᴜɴᴅ.",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        sess = _SESSIONS.setdefault(q.from_user.id, {})
        sess["catalog_data"] = cat.data
        comp = {s.get("title_slug") for s in await _list_completed()}
        lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                 f"📚 <b>{fb('ALL SERIES')}</b>", DIV, "",
                 f"📊 <code>{len(all_s)}</code> · ✅ <code>{len(comp)}</code>",
                 "", DIV2, ""]
        for s in all_s[:25]:
            mk = "✅" if s["title_slug"] in comp else "🎬"
            lines.append(f"{mk} <b>{_esc(s['title'])}</b> · <code>{s['file_count']}</code>")
        try:
            await client.edit_message_text(chat_id=q.message.chat.id,
                message_id=status.id, text="\n".join(lines),
                reply_markup=kb_series_list(all_s),
                parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception: pass
    except Exception as e: logger.exception(f"[AI] all: {e}")


@Client.on_callback_query(filters.regex(r"^ai:completed$"), group=-430)
async def cb_comp(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        items = await _list_completed(50)
        lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                 f"✅ <b>{fb('COMPLETED')}</b>", DIV, ""]
        if not items: lines.append("⚪ ɴᴏɴᴇ ʏᴇᴛ.")
        else:
            for it in items[:30]:
                ts = it.get("completed_at", 0)
                try: d = datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
                except Exception: d = "?"
                lines.append(f"✅ <b>{_esc(it.get('title'))}</b> · <code>{d}</code>")
        rows = [[InlineKeyboardButton(f"🔄 UNMARK · {(it.get('title') or '?')[:25]}",
                                       callback_data=f"ai:unmark:{it.get('title_slug')}")]
                for it in items[:10]]
        rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                     InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
        await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
        await q.answer()
    except Exception as e: logger.exception(f"[AI] comp: {e}")


@Client.on_callback_query(filters.regex(r"^ai:unmark:([a-z0-9_]+)$"), group=-430)
async def cb_unmark(client, q):
    try:
        slug = q.matches[0].group(1)
        ok = await _unmark_completed(slug)
        await q.answer("✅ ᴜɴᴍᴀʀᴋᴇᴅ" if ok else "❌ ɴᴏᴛ ꜰᴏᴜɴᴅ")
        await cb_comp(client, q)
    except Exception as e: logger.exception(f"[AI] unmark: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DELETE FILE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^ai:del_pick:([a-z0-9_]+):(\d+):(\d+):(\w+):(\d+)$"),
    group=-430)
async def cb_del_pick(client, q):
    try:
        slug = q.matches[0].group(1)
        sn = int(q.matches[0].group(2))
        ep_raw = int(q.matches[0].group(3))
        qual = q.matches[0].group(4)
        idx = int(q.matches[0].group(5))
        ep = ep_raw if ep_raw > 0 else None
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        qmap = ((series.get("seasons") or {}).get(sn) or {}).get(ep, {})
        f = qmap.get(qual)
        if not f: return await q.answer("⚠️ ǫᴜᴀʟɪᴛʏ ɴᴏᴛ ꜰᴏᴜɴᴅ",
                                          show_alert=True)
        ep_label = f"S{sn:02d}" + (f"E{ep:02d}" if ep else "")
        langs = "+".join(f.get("languages", [])) or "?"
        size = _fmt_size(f.get("file_size", 0))
        text = "\n".join([
            f"⚠️ <b>{fb('CONFIRM DELETE')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(series.get('title'))}</b> · <code>{ep_label}</code>",
            f"🎯 {sc('quality')} · <code>{qual}</code>",
            f"🌍 {sc('languages')} · <code>{langs}</code>",
            f"📦 {sc('size')} · <code>{size}</code>",
            "",
            DIV2, "",
            f"❗ <b>{sc('this cannot be undone')}</b>",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ YES, DELETE",
                callback_data=f"ai:del_go:{slug}:{sn}:"
                               f"{ep if ep is not None else 0}:{qual}:{idx}")],
            [InlineKeyboardButton("❌ CANCEL", callback_data=f"ai:epq:{slug}:{sn}:"
                                                              f"{ep if ep is not None else 0}")],
        ])
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] del_pick: {e}")


@Client.on_callback_query(
    filters.regex(r"^ai:del_go:([a-z0-9_]+):(\d+):(\d+):(\w+):(\d+)$"),
    group=-430)
async def cb_del_go(client, q):
    try:
        slug = q.matches[0].group(1)
        sn = int(q.matches[0].group(2))
        ep_raw = int(q.matches[0].group(3))
        qual = q.matches[0].group(4)
        idx = int(q.matches[0].group(5))
        ep = ep_raw if ep_raw > 0 else None
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        qmap = ((series.get("seasons") or {}).get(sn) or {}).get(ep, {})
        f = qmap.get(qual)
        if not f: return await q.answer("⚠️ ǫᴜᴀʟɪᴛʏ ɴᴏᴛ ꜰᴏᴜɴᴅ",
                                          show_alert=True)
        fid = f.get("file_id") or ""
        if not fid: return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇ ɪᴅ", show_alert=True)
        ok = await _delete_file_record(fid)
        if not ok: return await q.answer("❌ ᴅᴇʟᴇᴛᴇ ꜰᴀɪʟᴇᴅ", show_alert=True)

        # Remove from catalog
        del s["catalog_data"][slug]["seasons"][sn][ep][qual]
        # Update file_count
        s["catalog_data"][slug]["file_count"] = max(
            0, s["catalog_data"][slug]["file_count"] - 1)

        await q.answer("🗑️ ᴅᴇʟᴇᴛᴇᴅ")

        # Re-render the episode quality picker
        await cb_epq(client, q)
    except Exception as e:
        logger.exception(f"[AI] del_go: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# DAILY REPORT + BOOT
# ═══════════════════════════════════════════════════════════════════════════
_LAST_REPORT: Optional[str] = None


async def _daily_loop(client):
    global _LAST_REPORT
    await asyncio.sleep(120)
    while True:
        try:
            now = datetime.now(IST)
            key = now.strftime("%Y-%m-%d")
            on = await _get_setting("auto_mode", True)
            if (on and now.hour == DAILY_REPORT_HOUR
                    and now.minute < 5 and _LAST_REPORT != key):
                _LAST_REPORT = key
                await _send_report(client)
        except asyncio.CancelledError: break
        except Exception as e: logger.warning(f"[AI] daily: {e}")
        await asyncio.sleep(60)


async def _send_report(client):
    try:
        comp = await _count_completed()
        total = await _get_setting("total_series", 0)
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🎛️ <b>{fb('DAILY AI REPORT')}</b>", DIV, "",
            f"📅 <code>{_now_ist()}</code>", "",
            f"📚 {sc('total')} · <code>{_fmt_int(total)}</code>",
            f"✅ {sc('completed')} · <code>{_fmt_int(comp)}</code>",
            f"⏳ {sc('pending')} · <code>{_fmt_int(max(0, total - comp))}</code>",
            "", DIV2, "",
            f"📌 {sc('tap auto to review 3 series')}",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 AUTO", callback_data="ai:auto"),
             InlineKeyboardButton("✍️ MANUAL", callback_data="ai:manual")],
            [InlineKeyboardButton("🎛️ PANEL", callback_data="ai:main"),
             InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")]])
        for a in ADMINS:
            try:
                aid = int(a) if str(a).lstrip("-").isdigit() else None
                if not aid: continue
                await client.send_message(aid, text, reply_markup=kb,
                                           parse_mode=ParseMode.HTML,
                                           disable_web_page_preview=True)
            except Exception: pass
    except Exception as e: logger.warning(f"[AI] report: {e}")


@Client.on_callback_query(filters.regex(r"^ai:last_report$"), group=-430)
async def cb_last(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        comp = await _count_completed()
        total = await _get_setting("total_series", 0)
        await _safe_edit(q, "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{fb('STATUS')}</b>", DIV, "",
            f"📚 <code>{_fmt_int(total)}</code> · ✅ <code>{_fmt_int(comp)}</code>",
            "", f"🕒 <code>{_now_ist()}</code>"]), kb_back("ai:main"))
        await q.answer()
    except Exception as e: logger.exception(f"[AI] last: {e}")


async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(600); _cleanup_sessions()
        except asyncio.CancelledError: break
        except Exception: pass


_BOOTED = False

@Client.on_message(filters.private, group=-428)
async def _boot(client, message):
    global _BOOTED
    if _BOOTED: return
    _BOOTED = True
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_daily_loop(client))
        loop.create_task(_cleanup_loop())
        logger.info("[AI] loops started")
    except Exception as e: logger.warning(f"[AI] boot: {e}")


logger.info("🎛️ AI LIBRARIAN v4 LOADED — same engine as series group")
