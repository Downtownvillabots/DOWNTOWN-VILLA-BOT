# plugins/ai_librarian.py
"""
🎛️ AI LIBRARIAN v5 — Live tracking + Same DB engine as series_group

Features:
- Add Series → live 1-hour scan
- Auto-refresh every 30s
- Shows S##E## grid with 🟢/🟡/🔴 status
- Qualities detected per episode
- Mark complete when all episodes found
- Cancel anytime
"""
import asyncio
import logging
import os
import re
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

LIVE_DURATION_SEC = 3600          # 1 hour
LIVE_REFRESH_SEC = 30             # refresh every 30s
SESSION_TTL = 7200                # 2h session TTL

DIV = "━" * 26
DIV2 = "─" * 26

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

def _normalize(s: str) -> str:
    if not s: return ""
    s = s.strip().lower()
    s = re.sub(r"[.\-_/,;:]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()


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

def _prefs_coll():
    d = _get_db(); return d["ai_prefs"] if d is not None else None

def _settings_coll():
    d = _get_db(); return d["ai_settings"] if d is not None else None


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
    try: return await c.find({}).sort("completed_at", -1).to_list(limit)
    except Exception: return []

async def _count_completed():
    c = _completed_coll()
    if c is None: return 0
    try: return await c.count_documents({})
    except Exception: return 0


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

# ═══════════════════════════════════════════════════════════════════════════
# ENGINE SEARCH — SAME AS series_group.py
# ═══════════════════════════════════════════════════════════════════════════
async def _engine_search(title, season=None, language=None, quality=None):
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
        hits = result.hits if result is not None else None
        if not hits:
            result = await engine.search_any(norm)
            hits = result.hits if result is not None else None
        hits = hits or []

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
                "quality": (h_quality or "UNKNOWN"),
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


async def _smart_db_search(title):
    """Same as series_group — try shorter prefixes if full fails."""
    norm = _normalize(title)
    if not norm: return None
    words = norm.split()
    for i in range(len(words), max(0, len(words) - 4), -1):
        partial = " ".join(words[:i])
        hits = await _engine_search(partial)
        if hits:
            matched = hits[0].get("series_title") or hits[0].get("title") or partial
            logger.info(f"[AI] smart: {title!r} → {matched!r} ({len(hits)})")
            return {"matched_title": matched, "hits": hits}
    return None


# ═══════════════════════════════════════════════════════════════════════════
# LIGHT PARSER — SAME AS series_group.py
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
    """1 file per (season, episode, quality)."""
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
# SUMMARY — SAME AS series_group._summarize
# ═══════════════════════════════════════════════════════════════════════════
def _summarize(files):
    """Return {qualities, languages, seasons: {sn: [eps]}, total_files}."""
    qualities: Set[str] = set()
    languages: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)
    for f in files:
        q = f.get("quality") or "UNKNOWN"
        if q != "UNKNOWN": qualities.add(q)
        for l in (f.get("languages") or []): languages.add(l)
        s = f.get("season"); e = f.get("episode")
        if s is not None: seasons[s].add(e if e is not None else 0)
    return {
        "qualities": sorted(qualities, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True),
        "languages": sorted(languages),
        "seasons": {s: sorted(eps) for s, eps in seasons.items()},
        "total_files": len(files),
    }


# ═══════════════════════════════════════════════════════════════════════════
# CATALOG — groups files by season → episode → quality
# ═══════════════════════════════════════════════════════════════════════════
class SeriesCatalog:
    def __init__(self):
        # {slug: {"title": str, "seasons": {sn: {ep: {q: file}}}}}
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


# ═══════════════════════════════════════════════════════════════════════════
# TMDB — SAME AS series_group.py
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_get(path, params=None):
    if not TMDB_API_KEY: return None
    try:
        import aiohttp
    except ImportError: return None
    p = {"api_key": TMDB_API_KEY, "language": "en-US", **(params or {})}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://api.themoviedb.org/3{path}",
                                params=p, timeout=12) as r:
                if r.status != 200: return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[AI] tmdb: {e}"); return None


async def _tmdb_search_series(query):
    data = await _tmdb_get("/search/tv", {"query": query, "include_adult": "false"})
    if not data: return []
    out = []
    for it in (data.get("results") or [])[:8]:
        title = it.get("name") or it.get("original_name") or ""
        if not title: continue
        date = it.get("first_air_date") or ""
        out.append({
            "tmdb_id": it.get("id"), "title": title,
            "year": (date or "")[:4],
            "rating": it.get("vote_average", 0),
            "poster": it.get("poster_path"),
        })
    return out


async def _tmdb_series_details(tmdb_id):
    if not tmdb_id: return None
    return await _tmdb_get(f"/tv/{tmdb_id}", {})


def _tmdb_languages(details):
    langs = set()
    orig = (details.get("original_language") or "").lower()
    if orig: langs.add(orig)
    for sl in (details.get("spoken_languages") or []):
        code = (sl.get("iso_639_1") or "").lower()
        if code: langs.add(code)
    m = {"en":"English","hi":"Hindi","ta":"Tamil","te":"Telugu","ml":"Malayalam",
         "kn":"Kannada","bn":"Bengali","mr":"Marathi","pa":"Punjabi",
         "gu":"Gujarati","ur":"Urdu","ko":"Korean","ja":"Japanese",
         "zh":"Chinese","es":"Spanish","fr":"French","de":"German",
         "it":"Italian","pt":"Portuguese","ru":"Russian","tr":"Turkish",
         "ar":"Arabic","th":"Thai"}
    named = [m[c] for c in langs if c in m]
    named.sort(key=lambda x: (x != "English", x))
    return named or ["English"]


def _tmdb_seasons(details):
    """Return [{season, episodes, year}, ...] — season 0 skipped."""
    out = []
    for s in (details.get("seasons") or []):
        sn = s.get("season_number")
        if sn is None or sn == 0: continue
        out.append({
            "season": sn,
            "episodes": s.get("episode_count", 0),
            "year": (s.get("air_date") or "")[:4],
        })
    out.sort(key=lambda x: x["season"])
    return out


def _poster_url(path, size="w500"):
    if not path: return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


# ═══════════════════════════════════════════════════════════════════════════
# SESSION STORAGE
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}       # uid → session
_LIVE_TASKS: Dict[int, asyncio.Task] = {}       # uid → refresher task


def _new_session(uid, action, **data):
    # Kill existing live task for this user
    _kill_live_task(uid)
    _SESSIONS[uid] = {
        "action": action,
        "expires": time.time() + SESSION_TTL,
        **data,
    }


def _get_session(uid):
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s.get("expires", 0):
        _SESSIONS.pop(uid, None); return None
    return s


def _clear_session(uid):
    _kill_live_task(uid)
    _SESSIONS.pop(uid, None)


def _kill_live_task(uid):
    t = _LIVE_TASKS.pop(uid, None)
    if t and not t.done():
        try: t.cancel()
        except Exception: pass


def _cleanup_sessions():
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        s = _SESSIONS.get(uid) or {}
        if s.get("expires", 0) < now:
            _kill_live_task(uid)
            _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# LIVE REFRESHER — Background task per user
# ═══════════════════════════════════════════════════════════════════════════
async def _live_refresher(client, uid, chat_id, msg_id):
    """
    Loops for LIVE_DURATION_SEC, re-searching DB every LIVE_REFRESH_SEC,
    editing the message with updated grid.

    Stops when:
    - session is cleared/cancelled
    - 1 hour elapsed
    - all episodes found (auto-complete hint)
    """
    started = time.time()
    last_grid_signature = None
    consecutive_complete = 0

    try:
        # initial small delay
        await asyncio.sleep(2)

        while True:
            # Check elapsed
            elapsed = time.time() - started
            if elapsed >= LIVE_DURATION_SEC:
                logger.info(f"[AI-LIVE] {uid} session timed out")
                await _render_timeout(client, chat_id, msg_id, uid)
                return

            # Check session still alive
            sess = _get_session(uid)
            if not sess or sess.get("action") != "live_scan":
                logger.info(f"[AI-LIVE] {uid} session cancelled")
                return

            search_term = sess.get("search_term") or ""
            if not search_term:
                await asyncio.sleep(LIVE_REFRESH_SEC); continue

            # Re-search DB
            try:
                files = await _engine_search(search_term)
            except Exception as e:
                logger.warning(f"[AI-LIVE] search err: {e}")
                files = []

            cat = SeriesCatalog()
            for f in files:
                cat.add_file(f)

            # Update session catalog
            sess["catalog_data"] = cat.data

            # Compute TMDB expectation
            tmdb_seasons = sess.get("tmdb_seasons") or []
            total_expected = sum(s.get("episodes", 0) for s in tmdb_seasons)

            # Compute current stats
            stats = _compute_stats(cat.data, tmdb_seasons)
            grid_sig = _grid_signature(stats)

            # Only edit if something changed
            if grid_sig != last_grid_signature:
                last_grid_signature = grid_sig
                try:
                    await _render_live(client, chat_id, msg_id, uid,
                                       elapsed=elapsed,
                                       total_expected=total_expected)
                except Exception as e:
                    logger.debug(f"[AI-LIVE] render: {e}")

            # Auto-detect complete
            if total_expected > 0 and stats["total_found"] >= total_expected:
                consecutive_complete += 1
                if consecutive_complete >= 2:
                    logger.info(f"[AI-LIVE] {uid} all episodes found!")
                    return
            else:
                consecutive_complete = 0

            await asyncio.sleep(LIVE_REFRESH_SEC)
    except asyncio.CancelledError:
        logger.info(f"[AI-LIVE] {uid} task cancelled")
    except Exception as e:
        logger.exception(f"[AI-LIVE] crash: {e}")


def _compute_stats(catalog_data, tmdb_seasons):
    """
    Return:
      total_found: number of unique (sn, ep) with at least 1 quality
      seasons: {sn: {ep: {qualities: [q1, q2]}}}
      complete_episodes: [list of (sn,ep)]
      expected_map: {sn: {ep: True}}  from TMDB
    """
    total_found = 0
    seasons_out: Dict[int, Dict[int, Set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for slug, series in (catalog_data or {}).items():
        for sn, eps in (series.get("seasons") or {}).items():
            for ep, qmap in eps.items():
                if ep is None:
                    ep = 0
                for q in qmap.keys():
                    seasons_out[sn][ep].add(q)
                total_found += 1  # one per (sn, ep) unique pair

    expected_map: Dict[int, Set[int]] = {}
    for s in (tmdb_seasons or []):
        sn = s.get("season")
        eps = s.get("episodes", 0)
        if sn and eps:
            expected_map[sn] = set(range(1, eps + 1))

    return {
        "total_found": total_found,
        "seasons": {sn: dict(e) for sn, e in seasons_out.items()},
        "expected": expected_map,
    }


def _grid_signature(stats):
    """Hash-like signature for change detection."""
    parts = []
    for sn in sorted(stats["seasons"].keys()):
        eps = stats["seasons"][sn]
        for ep in sorted(eps.keys()):
            quals = sorted(eps[ep])
            parts.append(f"{sn}:{ep}:{','.join(quals)}")
    return "|".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_main(auto_on, completed, total):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 AUTO MODE ON" if auto_on else "🔴 AUTO MODE OFF",
                              callback_data="ai:toggle_auto")],
        [InlineKeyboardButton("➕ ADD SERIES (LIVE)", callback_data="ai:add")],
        [InlineKeyboardButton(f"📚 ALL SERIES ({total})", callback_data="ai:all"),
         InlineKeyboardButton(f"✅ COMPLETED ({completed})",
                              callback_data="ai:completed")],
        [InlineKeyboardButton("📊 STATUS", callback_data="ai:last_report"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="ai:main")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
    ])


def kb_live_controls(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH NOW", callback_data="ai:live_refresh"),
         InlineKeyboardButton("✅ MARK COMPLETE", callback_data="ai:live_complete")],
        [InlineKeyboardButton("❌ CANCEL LIVE", callback_data="ai:live_cancel")],
    ])


def kb_back(target="ai:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")]])


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


def kb_add_cancel():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")]])


def kb_suggestions(items):
    """TMDB suggestions — name in caps + rating."""
    rows = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating", 0)
        if len(title) > 42:
            title = title[:41] + "…"
        label = title
        if rating:
            label += f" ⭐{rating:.1f}"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"ai:pick:{i}")])
    rows.append([InlineKeyboardButton("✍️ SEARCH DB ONLY",
                                       callback_data="ai:search_db_only")])
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")])
    return InlineKeyboardMarkup(rows)


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
        f"➕ {sc('add series')} · ʟɪᴠᴇ 1-ʜᴏᴜʀ ꜱᴄᴀɴ",
        f"🔄 {sc('auto refresh')} · ᴇᴠᴇʀʏ 30 ꜱᴇᴄᴏɴᴅꜱ",
        f"🟢 {sc('green tick')} ᴡʜᴇɴ ꜰɪʟᴇ ꜰᴏᴜɴᴅ",
        "", DIV2,
        f"🕒 <code>{_now_ist()}</code>",
    ]), kb_main(auto_on, comp, total)


def _view_add_prompt():
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD SERIES')}</b>",
        DIV, "",
        f"📝 {sc('send the series name')}",
        "",
        f"📌 {sc('examples')}:",
        f"<code>breaking bad</code>",
        f"<code>game of thrones</code>",
        f"<code>money heist</code>",
        "", DIV2,
        f"💡 {sc('bot will search tmdb + your db')}",
        f"💡 {sc('then start live 1-hour scan')}",
    ])


def _view_searching(query):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('SEARCHING')}</b>",
        DIV, "",
        f"📝 <code>{_esc(query)}</code>",
        "",
        f"📌 {sc('checking tmdb + your db')}...",
    ])


def _view_live_header(title, year, elapsed, total_expected, stats):
    """Top section of the live message."""
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    remaining = max(0, LIVE_DURATION_SEC - int(elapsed))
    rem_min = remaining // 60

    found = stats["total_found"]
    seasons_found = len(stats["seasons"])

    # Progress bar
    if total_expected > 0:
        pct = min(100.0, found / total_expected * 100)
    else:
        pct = 0

    bar = _progress_bar(pct)

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔴 <b>{fb('LIVE SCAN')}</b> · ⏱️ <code>{minutes:02d}:{seconds:02d}</code>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>"
        + (f" <code>({year})</code>" if year else ""),
        "",
        f"<code>{bar}</code>",
        "",
        f"📁 {sc('found')} · <code>{found}</code>"
        + (f" / <code>{total_expected}</code>" if total_expected else ""),
        f"📺 {sc('seasons')} · <code>{seasons_found}</code>",
        f"⏳ {sc('ends in')} · <code>{rem_min} ᴍɪɴ</code>",
        "", DIV2, "",
    ]
    return "\n".join(lines)


def _view_live_grid(stats, tmdb_seasons):
    """Renders the episode grid with green/yellow/red ticks."""
    seasons_data = stats["seasons"]
    expected = stats["expected"]

    # Determine the full set of seasons to render
    all_seasons = set(seasons_data.keys()) | set(expected.keys())
    if not all_seasons:
        return "⚪ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ꜰᴏᴜɴᴅ ʏᴇᴛ..."

    lines = []
    for sn in sorted(all_seasons):
        eps_found = seasons_data.get(sn, {})
        eps_expected = expected.get(sn)

        # Header for the season
        if eps_expected:
            header = (f"📺 <b>Season {sn:02d}</b> · "
                      f"<code>{len(eps_found)}/{len(eps_expected)}</code>")
        else:
            header = (f"📺 <b>Season {sn:02d}</b> · "
                      f"<code>{len(eps_found)} ᴇᴘɪꜱᴏᴅᴇꜱ</code>")
        lines.append(header)

        # Determine which episodes to show
        if eps_expected:
            episode_set = sorted(eps_expected)
        else:
            episode_set = sorted(eps_found.keys())

        if not episode_set:
            lines.append("   ⚪ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ʏᴇᴛ")
            lines.append("")
            continue

        for ep in episode_set:
            quals = sorted(eps_found.get(ep, set()),
                           key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
            if quals:
                icon = "🟢"
                q_str = " ".join(f"<code>{q}</code>" for q in quals[:4])
                if len(quals) > 4:
                    q_str += f" +{len(quals)-4}"
            else:
                icon = "🔴"
                q_str = "<i>—</i>"
            lines.append(f"   {icon} <b>E{ep:02d}</b> · {q_str}")

        lines.append("")

    lines.append(DIV2)
    lines.append(f"🟢 = {sc('available')}   🔴 = {sc('missing')}")
    return "\n".join(lines)


def _view_live(title, year, elapsed, total_expected, stats, tmdb_seasons):
    """Combine header + grid."""
    header = _view_live_header(title, year, elapsed,
                               total_expected, stats)
    grid = _view_live_grid(stats, tmdb_seasons)
    return header + grid


def _view_timeout(title):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('SESSION ENDED')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        "",
        f"📌 {sc('1-hour live window closed')}",
        f"📌 {sc('tap add series again to restart')}",
    ])


def _progress_bar(p, w=16):
    p = max(0.0, min(100.0, float(p)))
    filled = int(w * p / 100); empty = w - filled
    block = "🟩" if p >= 75 else ("🟨" if p >= 50 else ("🟧" if p >= 25 else "🟥"))
    return block * filled + "⬛" * empty + f"  {p:.0f}%"


# ═══════════════════════════════════════════════════════════════════════════
# RENDER HELPERS
# ═══════════════════════════════════════════════════════════════════════════
async def _safe_edit(q_or_msg, text, kb=None):
    try:
        m = getattr(q_or_msg, "message", q_or_msg)
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                           disable_web_page_preview=True)
        return True
    except MessageNotModified:
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            m = getattr(q_or_msg, "message", q_or_msg)
            await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
            return True
        except Exception: return False
    except Exception as e:
        logger.debug(f"[AI] edit: {e}")
        return False


async def _edit_by_ids(client, chat_id, msg_id, text, kb=None):
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified: return True
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception: return False
    except Exception as e:
        logger.debug(f"[AI] edit_by_ids: {e}")
        return False


async def _render_live(client, chat_id, msg_id, uid, elapsed, total_expected):
    sess = _get_session(uid)
    if not sess: return

    title = sess.get("title") or "?"
    year = sess.get("year") or ""
    catalog_data = sess.get("catalog_data") or {}
    tmdb_seasons = sess.get("tmdb_seasons") or []

    stats = _compute_stats(catalog_data, tmdb_seasons)
    text = _view_live(title, year, elapsed, total_expected, stats, tmdb_seasons)
    kb = kb_live_controls(uid)

    await _edit_by_ids(client, chat_id, msg_id, text, kb)


async def _render_timeout(client, chat_id, msg_id, uid):
    sess = _get_session(uid)
    title = (sess or {}).get("title") or "?"
    try:
        await _edit_by_ids(client, chat_id, msg_id,
                           _view_timeout(title),
                           kb_back("ai:main"))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["ai", "librarian", "ailib"]) & filters.private,
    group=-430,
)
async def cmd_ai(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        _clear_session(message.from_user.id)
        text, kb = await _view_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[AI] /ai: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:main$"), group=-430)
async def cb_main(client, q):
    try:
        _clear_session(q.from_user.id)
        text, kb = await _view_main()
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] cb_main: {e}")


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
    try:
        cur = await _get_setting("auto_mode", True)
        await _set_setting("auto_mode", not cur)
        await q.answer("🟢 ᴀᴜᴛᴏ ᴏɴ" if not cur else "🔴 ᴀᴜᴛᴏ ᴏꜰꜰ")
        text, kb = await _view_main()
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[AI] toggle: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ADD SERIES  →  TMDB suggest  →  start live
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:add$"), group=-430)
async def cb_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        _new_session(q.from_user.id, "await_add_name",
                     chat_id=q.message.chat.id,
                     msg_id=q.message.id)
        await _safe_edit(q, _view_add_prompt(), kb_add_cancel())
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] add: {e}")


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-429,
)
async def ai_add_input(client, message):
    """Catches the series name admin typed."""
    if not message.from_user: return
    if not _is_admin(message.from_user.id): return

    s = _get_session(message.from_user.id)
    if not s or s.get("action") != "await_add_name":
        return

    try: message.stop_propagation()
    except Exception: pass

    query = (message.text or "").strip()
    if len(query) < 2:
        return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")

    uid = message.from_user.id
    chat_id = message.chat.id

    # Kill previous, keep an "await pick" session
    _new_session(uid, "await_pick",
                 query=query,
                 chat_id=chat_id,
                 msg_id=s.get("msg_id"))

    loading = await message.reply_text(_view_searching(query),
                                        parse_mode=ParseMode.HTML)

    # ── 1. TMDB suggest first ────────────────────────────────────────────
    suggestions = await _tmdb_search_series(query)

    if suggestions:
        _new_session(uid, "await_pick",
                     query=query,
                     suggestions=suggestions,
                     chat_id=chat_id,
                     msg_id=loading.id)
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🔎 <b>{fb('TMDB SUGGESTIONS')}</b>",
            DIV, "",
            f"📝 <code>{_esc(query)}</code>", "",
            f"📌 {sc('tap a title to start live scan')}",
            "", DIV2, "",
        ]
        for i, it in enumerate(suggestions, 1):
            t = it.get("title") or "?"
            yr = it.get("year") or ""
            r = it.get("rating", 0)
            lines.append(
                f"<b>{i}.</b> <b>{_esc(t)}</b>"
                + (f" <code>({yr})</code>" if yr else "")
                + (f" · ⭐ {r:.1f}" if r else "")
            )
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=loading.id,
                text="\n".join(lines),
                reply_markup=kb_suggestions(suggestions),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"[AI] suggest render: {e}")
        return

    # ── 2. No TMDB → scan DB directly ────────────────────────────────────
    await _start_live_scan(client, uid, chat_id, loading.id,
                            title=query, year="",
                            tmdb_seasons=[], matched_title=None)


@Client.on_callback_query(filters.regex(r"^ai:pick:(\d+)$"), group=-430)
async def cb_pick(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s or s.get("action") != "await_pick":
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

        items = s.get("suggestions") or []
        if idx < 0 or idx >= len(items):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen = items[idx]
        title = chosen.get("title") or ""
        year = chosen.get("year") or ""
        tmdb_id = chosen.get("tmdb_id")

        await q.answer("🔍 ꜱᴛᴀʀᴛɪɴɢ ʟɪᴠᴇ ꜱᴄᴀɴ...")

        # Fetch TMDB season list
        tmdb_seasons = []
        if tmdb_id:
            details = await _tmdb_series_details(tmdb_id)
            if details:
                tmdb_seasons = _tmdb_seasons(details)

        await _start_live_scan(client, q.from_user.id,
                                q.message.chat.id, q.message.id,
                                title=title, year=year,
                                tmdb_seasons=tmdb_seasons,
                                matched_title=title)
    except Exception as e:
        logger.exception(f"[AI] pick: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:search_db_only$"), group=-430)
async def cb_search_db_only(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        s = _get_session(q.from_user.id)
        if not s or s.get("action") != "await_pick":
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        query = s.get("query") or ""

        await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ ᴅʙ...")
        await _start_live_scan(client, q.from_user.id,
                                q.message.chat.id, q.message.id,
                                title=query, year="",
                                tmdb_seasons=[],
                                matched_title=query)
    except Exception as e:
        logger.exception(f"[AI] search_db_only: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# START LIVE SCAN  — core engine
# ═══════════════════════════════════════════════════════════════════════════
async def _start_live_scan(client, uid, chat_id, msg_id,
                            title, year, tmdb_seasons, matched_title=None):
    """
    Kick off the 1-hour live scan for this user.
    Uses _engine_search (same as series_group).
    """
    search_term = matched_title or title
    logger.info(f"[AI-LIVE] starting for {title!r} (search={search_term!r})")

    # First search immediately so UI is not empty
    try:
        files = await _engine_search(search_term)
    except Exception as e:
        logger.warning(f"[AI-LIVE] initial search: {e}")
        files = []

    cat = SeriesCatalog()
    for f in files:
        cat.add_file(f)

    # If DB matched a different title, adopt that for display
    db_title = title
    if files:
        first = files[0]
        db_title = first.get("series_title") or first.get("title") or title

    # Save session
    _new_session(uid, "live_scan",
                 search_term=search_term,
                 title=db_title,
                 year=year,
                 tmdb_seasons=tmdb_seasons or [],
                 catalog_data=cat.data,
                 chat_id=chat_id,
                 msg_id=msg_id,
                 started_at=time.time())

    # Initial render
    total_expected = sum(s.get("episodes", 0) for s in (tmdb_seasons or []))
    await _render_live(client, chat_id, msg_id, uid,
                        elapsed=0, total_expected=total_expected)

    # Spawn refresher task
    _kill_live_task(uid)
    task = asyncio.create_task(
        _live_refresher(client, uid, chat_id, msg_id)
    )
    _LIVE_TASKS[uid] = task


# ═══════════════════════════════════════════════════════════════════════════
# LIVE CONTROLS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:live_refresh$"), group=-430)
async def cb_live_refresh(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = q.from_user.id
        sess = _get_session(uid)
        if not sess or sess.get("action") != "live_scan":
            return await q.answer("⏱️ ɴᴏ ʟɪᴠᴇ ꜱᴇꜱꜱɪᴏɴ", show_alert=True)

        await q.answer("🔄 ʀᴇꜰʀᴇꜱʜɪɴɢ...")

        search_term = sess.get("search_term") or ""
        files = await _engine_search(search_term)

        cat = SeriesCatalog()
        for f in files:
            cat.add_file(f)
        sess["catalog_data"] = cat.data

        tmdb_seasons = sess.get("tmdb_seasons") or []
        total_expected = sum(s.get("episodes", 0) for s in tmdb_seasons)
        elapsed = time.time() - sess.get("started_at", time.time())

        await _render_live(client, q.message.chat.id, q.message.id, uid,
                            elapsed=elapsed,
                            total_expected=total_expected)
    except Exception as e:
        logger.exception(f"[AI] live_refresh: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:live_cancel$"), group=-430)
async def cb_live_cancel(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = q.from_user.id
        sess = _get_session(uid)
        if not sess or sess.get("action") != "live_scan":
            _clear_session(uid)
            await q.answer("✅ ᴄᴀɴᴄᴇʟʟᴇᴅ")
            text, kb = await _view_main()
            await _safe_edit(q, text, kb)
            return

        title = sess.get("title") or "?"
        _clear_session(uid)

        await q.answer("❌ ʟɪᴠᴇ ᴄᴀɴᴄᴇʟʟᴇᴅ")
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"❌ <b>{fb('LIVE CANCELLED')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            "",
            f"📌 {sc('no changes were saved')}",
            f"📌 {sc('tap add series to restart')}",
        ])
        await _safe_edit(q, text, kb_back("ai:main"))
    except Exception as e:
        logger.exception(f"[AI] live_cancel: {e}")


@Client.on_callback_query(filters.regex(r"^ai:live_complete$"), group=-430)
async def cb_live_complete(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = q.from_user.id
        sess = _get_session(uid)
        if not sess or sess.get("action") != "live_scan":
            return await q.answer("⏱️ ɴᴏ ʟɪᴠᴇ ꜱᴇꜱꜱɪᴏɴ", show_alert=True)

        title = sess.get("title") or "?"
        catalog_data = sess.get("catalog_data") or {}

        # Compute slug from title
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if not slug:
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ᴛɪᴛʟᴇ", show_alert=True)

        # Count total files
        total_files = 0
        for series in catalog_data.values():
            total_files += series.get("file_count", 0)

        ok = await _mark_completed(title, slug, total_files)
        if not ok:
            return await q.answer("❌ ꜱᴀᴠᴇ ꜰᴀɪʟᴇᴅ", show_alert=True)

        _clear_session(uid)

        await q.answer("✅ ᴍᴀʀᴋᴇᴅ ᴄᴏᴍᴘʟᴇᴛᴇ")
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{fb('MARKED COMPLETE')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            f"📁 <code>{_fmt_int(total_files)}</code> ꜰɪʟᴇꜱ",
            f"📅 <code>{_now_ist()}</code>",
            "", DIV2,
            f"📌 {sc('will be skipped in future scans')}",
        ])
        await _safe_edit(q, text, kb_back("ai:main"))
    except Exception as e:
        logger.exception(f"[AI] live_complete: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# VIEW / LIST SERIES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:all$"), group=-430)
async def cb_all(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")

        # Build catalog from recent engine search on completed slugs?
        # Simplest: build from all completed + discovered
        comp = await _list_completed(200)
        if not comp:
            await _safe_edit(q,
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n\n⚪ ɴᴏ ꜱᴇʀɪᴇꜱ ʏᴇᴛ.",
                kb_back("ai:main"))
            return

        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📚 <b>{fb('ALL SERIES')}</b>",
            DIV, "",
            f"📊 <code>{len(comp)}</code> ᴛᴏᴛᴀʟ",
            "", DIV2, "",
        ]
        for it in comp[:25]:
            lines.append(
                f"✅ <b>{_esc(it.get('title'))}</b> · "
                f"<code>{it.get('total_files', 0)}</code>"
            )
        await _safe_edit(q, "\n".join(lines), kb_back("ai:main"))
    except Exception as e:
        logger.exception(f"[AI] all: {e}")


@Client.on_callback_query(filters.regex(r"^ai:completed$"), group=-430)
async def cb_completed(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        await _render_completed(q)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] completed: {e}")


async def _render_completed(q):
    items = await _list_completed(50)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('COMPLETED')}</b>",
        DIV, "",
    ]
    if not items:
        lines.append("⚪ ɴᴏɴᴇ ʏᴇᴛ.")
    else:
        for it in items[:30]:
            ts = it.get("completed_at", 0)
            try:
                d = datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
            except Exception:
                d = "?"
            lines.append(
                f"✅ <b>{_esc(it.get('title'))}</b> · <code>{d}</code>"
            )

    rows = [
        [InlineKeyboardButton(
            f"🔄 UNMARK · {(it.get('title') or '?')[:25]}",
            callback_data=f"ai:unmark:{it.get('title_slug')}",
        )]
        for it in items[:10]
    ]
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close"),
    ])
    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^ai:unmark:([a-z0-9_]+)$"), group=-430)
async def cb_unmark(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        slug = q.matches[0].group(1)
        ok = await _unmark_completed(slug)
        await q.answer("✅ ᴜɴᴍᴀʀᴋᴇᴅ" if ok else "❌ ɴᴏᴛ ꜰᴏᴜɴᴅ")
        await _render_completed(q)
    except Exception as e:
        logger.exception(f"[AI] unmark: {e}")


@Client.on_callback_query(filters.regex(r"^ai:last_report$"), group=-430)
async def cb_last(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        comp = await _count_completed()
        total = await _get_setting("total_series", 0)
        await _safe_edit(q, "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{fb('STATUS')}</b>",
            DIV, "",
            f"📚 <code>{_fmt_int(total)}</code> · "
            f"✅ <code>{_fmt_int(comp)}</code>",
            "",
            f"🕒 <code>{_now_ist()}</code>",
        ]), kb_back("ai:main"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] last: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# VIEW SINGLE SERIES (read-only, from completed list)
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:view:([a-z0-9_]+)$"), group=-430)
async def cb_view(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        slug = q.matches[0].group(1)
        # Look up completed entry
        c = _completed_coll()
        if c is None:
            return await q.answer("⚠️ ᴅʙ ᴇʀʀᴏʀ", show_alert=True)
        doc = await c.find_one({"title_slug": slug})
        if not doc:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = doc.get("title") or slug
        total_files = doc.get("total_files", 0)
        ts = doc.get("completed_at", 0)
        try:
            completed_str = datetime.fromtimestamp(ts, IST).strftime(
                "%d %b %Y · %H:%M IST")
        except Exception:
            completed_str = "?"

        await _safe_edit(q, "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{_esc(title)}</b>",
            DIV, "",
            f"📁 {sc('total files')} · <code>{_fmt_int(total_files)}</code>",
            f"📅 {sc('completed')} · <code>{completed_str}</code>",
            "", DIV2,
            f"💡 {sc('start a live scan to see current status')}",
        ]), kb_back("ai:main"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] view: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND CLEANUP
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception: pass


_BOOTED = False


@Client.on_message(filters.private, group=-428)
async def _boot(client, message):
    global _BOOTED
    if _BOOTED:
        return
    _BOOTED = True
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_cleanup_loop())
        logger.info("[AI] cleanup loop started")
    except Exception as e:
        logger.warning(f"[AI] boot: {e}")


logger.info("🎛️ AI LIBRARIAN v5 LOADED — LIVE SCAN + SAME DB ENGINE")




