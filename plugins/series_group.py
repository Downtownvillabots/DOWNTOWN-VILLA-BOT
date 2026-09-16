# plugins/series_group.py
"""
🎬 DOWNTOWN VILLA — SERIES GROUP

Dedicated series search group with:
- TMDB suggestions (spelling correction)
- Language picker (from TMDB metadata)
- Season picker (from TMDB)
- Quality picker (from DB / admin-set)
- Episode delivery to user PM
- Admin: captions, buttons, per-series quality prefs
"""
import asyncio
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait, UserIsBlocked
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

SERIES_GROUP_ID_RAW = os.getenv("SERIES_GROUP_ID", "0").strip()
try:
    SERIES_GROUP_ID = int(SERIES_GROUP_ID_RAW) or None
except (TypeError, ValueError):
    SERIES_GROUP_ID = None

SESSION_TTL = 900
DELIVER_CONCURRENCY = 3
DELIVER_BATCH_DELAY = 0.6
MAX_EPISODES_PER_PICK = 100

DIV = "━" * 26
DIV2 = "─" * 26

QUALITY_RANK = {
    "4320P": 100, "8K": 100, "2160P": 90, "4K": 90, "UHD": 90,
    "1440P": 80, "2K": 80, "1080P": 70, "FULLHD": 70, "FHD": 70,
    "720P": 60, "HD": 60, "576P": 50, "480P": 40, "SD": 40,
    "360P": 30, "240P": 20, "UNKNOWN": 25,
}

# Default caption (admin-editable)
DEFAULT_EPISODE_CAPTION = (
    "🎬 <b>{series}</b>\n"
    "📺 <b>Season {season:02d} · Episode {episode:02d}</b>\n"
    "🎯 Quality: <code>{quality}</code>\n"
    "🌍 Language: <code>{language}</code>\n"
    "📦 Size: <code>{size}</code>\n"
    "\n"
    "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
)

# Fancy fonts
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


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════
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

def _get_client():
    try: return db_manager._client or db_manager.client
    except Exception: return None


def _sgroup_coll():
    d = _get_db()
    return d["series_group"] if d is not None else None


async def _get_caption() -> str:
    c = _sgroup_coll()
    if c is None: return DEFAULT_EPISODE_CAPTION
    try:
        doc = await c.find_one({"_id": "caption"}) or {}
        return doc.get("template") or DEFAULT_EPISODE_CAPTION
    except Exception: return DEFAULT_EPISODE_CAPTION


async def _set_caption(template: str) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "caption"},
                           {"$set": {"template": template,
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_buttons() -> List[Dict[str, Any]]:
    """Extra buttons attached to each delivered episode."""
    c = _sgroup_coll()
    if c is None: return []
    try:
        doc = await c.find_one({"_id": "buttons"}) or {}
        return list(doc.get("list") or [])
    except Exception: return []


async def _set_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "buttons"},
                           {"$set": {"list": buttons,
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _get_series_pref(slug: str) -> Dict[str, Any]:
    """Per-series preference: which qualities to offer."""
    c = _sgroup_coll()
    if c is None: return {}
    try:
        doc = await c.find_one({"title_slug": slug}) or {}
        return dict(doc)
    except Exception: return {}


async def _set_series_pref(slug: str, title: str, qualities: List[str]) -> bool:
    c = _sgroup_coll()
    if c is None: return False
    try:
        await c.update_one({"title_slug": slug},
                           {"$set": {"title_slug": slug, "title": title,
                                     "qualities": list(qualities),
                                     "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


async def _list_series_prefs() -> List[Dict[str, Any]]:
    c = _sgroup_coll()
    if c is None: return []
    try:
        cursor = c.find({"title_slug": {"$exists": True}}).sort("updated_at", -1)
        return await cursor.to_list(length=200)
    except Exception: return []


# ═══════════════════════════════════════════════════════════════════════════
# FILE COLLECTIONS (same as AI Librarian)
# ═══════════════════════════════════════════════════════════════════════════
async def _all_file_collections():
    results = []
    seen_ids = set()

    def _add(name, c):
        try: key = str(id(c))
        except Exception: key = name
        if key in seen_ids: return
        if not hasattr(c, "find"): return
        seen_ids.add(key)
        results.append((name, c))

    try:
        from database.media.files import media_files_repo
        for attr in ("collection", "_coll", "_collection", "coll", "col"):
            c = getattr(media_files_repo, attr, None)
            if c is not None and hasattr(c, "find"):
                _add(f"media_files_repo.{attr}", c); break
    except Exception: pass

    try:
        from database.media.routing import media_router
        for attr in ("_dbs", "_shards", "shards", "_collections"):
            val = getattr(media_router, attr, None)
            if isinstance(val, dict):
                for k, v in val.items():
                    if hasattr(v, "find"): _add(f"router.{k}", v)
                    elif hasattr(v, "list_collection_names"):
                        for cn in ("media_files", "files", "media"):
                            try: _add(f"router.{k}.{cn}", v[cn])
                            except Exception: pass
            elif isinstance(val, (list, tuple)):
                for i, v in enumerate(val):
                    if hasattr(v, "find"): _add(f"router.shard_{i}", v)
    except Exception: pass

    client = _get_client()
    if client is not None:
        try: dbs = await client.list_database_names()
        except Exception: dbs = []
        patterns = ("media", "file", "shard", "movie", "series")
        for db_name in dbs:
            if db_name in ("admin", "local", "config"): continue
            try:
                db = client[db_name]
                colls = await db.list_collection_names()
            except Exception: continue
            for cname in colls:
                cl = cname.lower()
                if cname.startswith(("ai_", "series_group", "ott_")): continue
                if any(p in cl for p in patterns):
                    try: _add(f"{db_name}.{cname}", db[cname])
                    except Exception: pass

    if not results:
        d = _get_db()
        if d is not None:
            try:
                colls = await d.list_collection_names()
                for cname in colls:
                    cl = cname.lower()
                    if cname.startswith(("ai_", "series_group", "ott_")): continue
                    if any(p in cl for p in ("media", "file", "shard")):
                        try: _add(f"db.{cname}", d[cname])
                        except Exception: pass
            except Exception: pass

    return results


# ═══════════════════════════════════════════════════════════════════════════
# FILENAME PARSER (compact — same logic as AI Librarian)
# ═══════════════════════════════════════════════════════════════════════════
SE_PATTERNS = [
    re.compile(r"[sS](\d{1,2})[\s._-]?[eE][pP]?(\d{1,3})"),
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?[eE]pisode[\s._-]?(\d{1,3})"),
    re.compile(r"[sS](\d{1,2})[\s._-]+[eE](\d{1,3})"),
]
SEASON_ONLY = [
    re.compile(r"\b[sS](\d{1,2})\b(?![\s._-]?[eE])"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})\b(?![\s._-]?[eE])"),
]

QUALITY_MARKERS = [
    ("4320p", "4320P"), ("2160p", "2160P"), ("4k", "4K"), ("uhd", "UHD"),
    ("1440p", "1440P"), ("1080p", "1080P"), ("fullhd", "1080P"), ("fhd", "1080P"),
    ("720p", "720P"), ("576p", "576P"), ("480p", "480P"), ("360p", "360P"),
    ("240p", "240P"),
]

LANGUAGE_ALIASES = {
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

NOISE_WORDS = {
    "web", "webdl", "webrip", "bluray", "bdrip", "brrip", "hdtv",
    "x264", "x265", "h264", "h265", "hevc", "avc", "aac", "ac3",
    "dts", "ddp", "dd", "truehd", "atmos", "remux", "proper", "repack",
    "extended", "unrated", "internal", "dual", "multi", "subs", "sub",
    "hdr", "sdr", "dolby", "imax", "mkv", "mp4", "avi", "mov", "webm",
}


def _smart_title_case(s):
    if not s: return ""
    small = {"of", "the", "and", "or", "a", "an", "in", "on", "at",
             "to", "for", "by", "with", "from"}
    parts = s.split()
    if not parts: return ""
    out = [parts[0].capitalize()]
    for w in parts[1:]:
        out.append(w.lower() if w.lower() in small else w.capitalize())
    return " ".join(out)


def parse_filename(filename: str) -> Dict[str, Any]:
    result = {"raw": filename, "title": "", "title_slug": "",
              "year": None, "season": None, "episode": None,
              "quality": None, "languages": [],
              "is_series": False, "size_from_name": 0}
    if not filename: return result

    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts)$", "",
                  name, flags=re.I)
    work = name
    wl = work.lower()

    season = episode = None
    for pat in SE_PATTERNS:
        m = pat.search(work)
        if m:
            try:
                season = int(m.group(1)); episode = int(m.group(2)); break
            except Exception: continue
    if season is None:
        for pat in SEASON_ONLY:
            m = pat.search(work)
            if m:
                try: season = int(m.group(1)); break
                except Exception: continue

    result["season"] = season
    result["episode"] = episode

    for marker, label in QUALITY_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", wl):
            result["quality"] = label; break

    langs = []
    for ln, aliases in LANGUAGE_ALIASES.items():
        for a in aliases:
            if re.search(r"\b" + re.escape(a) + r"\b", wl):
                if ln not in langs: langs.append(ln)
                break
    result["languages"] = langs

    if season is not None or episode is not None:
        result["is_series"] = True

    tw = work
    for pat in SE_PATTERNS: tw = pat.sub(" ", tw)
    for pat in SEASON_ONLY: tw = pat.sub(" ", tw)
    for marker, _ in QUALITY_MARKERS:
        tw = re.sub(r"\b" + re.escape(marker) + r"\b", " ", tw, flags=re.I)
    for lang in langs:
        for a in LANGUAGE_ALIASES.get(lang, []):
            tw = re.sub(r"\b" + re.escape(a) + r"\b", " ", tw, flags=re.I)
    for noise in NOISE_WORDS:
        tw = re.sub(r"\b" + re.escape(noise) + r"\b", " ", tw, flags=re.I)

    tw = re.sub(r"[-_.\s]*@\w+\b", " ", tw)
    tw = re.sub(r"[-_.\s]*\[[^\]]{1,40}\]", " ", tw)
    tw = re.sub(r"[-_.\s]*(?:rarbg|eztv|yts|yify|galaxyrg|psa|hon3y|bolly4u|"
                r"thetvshare|tvshare|hdhub4u|mkvcage|shaanig|tamilrockers)\b",
                " ", tw, flags=re.I)
    tw = re.sub(r"[._\-]+", " ", tw)
    tw = re.sub(r"\s+", " ", tw).strip()
    parts = [p for p in tw.split() if len(p) > 1]
    result["title"] = _smart_title_case(" ".join(parts))
    result["title_slug"] = re.sub(r"[^a-z0-9]+", "_",
                                   result["title"].lower()).strip("_")
    return result


def _extract_filename(doc: Dict[str, Any]) -> str:
    for key in ("file_name", "filename", "title", "name", "file_title",
                "caption", "file_caption", "media_title", "text"):
        v = doc.get(key)
        if isinstance(v, str) and v.strip(): return v
    for k, v in doc.items():
        if k in ("_id","chat_id","message_id","msg_id","file_id",
                 "file_unique_id","file_size","size"): continue
        if isinstance(v, str) and len(v) > 5:
            if any(x in v.lower() for x in
                   (".mkv",".mp4",".avi",".mov",".webm",".ts",".m4v")):
                return v
    return ""


# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _new_session(uid: int, **data) -> str:
    sid = secrets.token_urlsafe(6)[:8]
    _SESSIONS[uid] = {"sid": sid, "data": data,
                      "expires": time.time() + SESSION_TTL}
    return sid


def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(uid, None); return None
    return s


def _clear_session(uid: int) -> None:
    _SESSIONS.pop(uid, None)


def _cleanup_sessions():
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# TMDB API
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_get(path: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    if not TMDB_API_KEY: return None
    try:
        import aiohttp
    except ImportError:
        return None
    p = {"api_key": TMDB_API_KEY, "language": "en-US", **(params or {})}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://api.themoviedb.org/3{path}",
                                params=p, timeout=12) as r:
                if r.status != 200: return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[SG] tmdb {path}: {e}"); return None


async def _tmdb_search_series(query: str) -> List[Dict[str, Any]]:
    data = await _tmdb_get("/search/tv", {"query": query, "include_adult": "false"})
    if not data: return []
    out = []
    for it in (data.get("results") or [])[:8]:
        title = it.get("name") or it.get("original_name") or ""
        if not title: continue
        date = it.get("first_air_date") or ""
        out.append({
            "tmdb_id": it.get("id"),
            "title": title,
            "year": (date or "")[:4],
            "rating": it.get("vote_average", 0),
            "poster": it.get("poster_path"),
            "overview": (it.get("overview") or "")[:200],
        })
    return out


async def _tmdb_series_details(tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Get full series info including seasons + languages."""
    return await _tmdb_get(f"/tv/{tmdb_id}",
                            {"append_to_response": "content_ratings"})


def _tmdb_languages_from_details(details: Dict[str, Any]) -> List[str]:
    """Extract available languages for a series."""
    langs = set()
    # Original language
    orig = (details.get("original_language") or "").lower()
    if orig:
        langs.add(orig)
    # Spoken languages
    for sl in (details.get("spoken_languages") or []):
        code = (sl.get("iso_639_1") or "").lower()
        if code: langs.add(code)
    # Map codes to names
    code_to_name = {
        "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
        "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
        "pa": "Punjabi", "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
        "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "fr": "French",
        "de": "German", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
        "tr": "Turkish", "ar": "Arabic", "th": "Thai", "vi": "Vietnamese",
        "id": "Indonesian",
    }
    named = [code_to_name[c] for c in langs if c in code_to_name]
    named.sort(key=lambda x: (x != "English", x))  # English first
    return named or ["English"]


def _tmdb_seasons_from_details(details: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get seasons list."""
    out = []
    for s in (details.get("seasons") or []):
        sn = s.get("season_number")
        if sn is None or sn == 0:  # skip specials
            continue
        out.append({
            "season": sn,
            "episodes": s.get("episode_count", 0),
            "year": (s.get("air_date") or "")[:4],
            "name": s.get("name") or f"Season {sn}",
        })
    out.sort(key=lambda x: x["season"])
    return out


def _poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path: return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


# ═══════════════════════════════════════════════════════════════════════════
# LOCAL DB — find series episodes matching series + language + quality
# ═══════════════════════════════════════════════════════════════════════════
async def _find_series_files(title_slug: str, language: Optional[str] = None,
                              quality: Optional[str] = None,
                              season: Optional[int] = None) -> List[Dict[str, Any]]:
    """Scan DB for files matching a series (uses engine first, then raw)."""
    all_files: List[Dict[str, Any]] = []
    colls = await _all_file_collections()
    for cname, coll in colls:
        try:
            async for doc in coll.find({}):
                fname = _extract_filename(doc)
                if not fname: continue
                p = parse_filename(fname)
                if not p.get("is_series"): continue
                slug = p.get("title_slug", "")
                if title_slug not in slug and slug not in title_slug:
                    continue
                if season is not None and p.get("season") != season:
                    continue
                if language and language not in (p.get("languages") or []):
                    continue
                if quality and quality != p.get("quality"):
                    continue
                all_files.append({
                    "file_id": doc.get("file_id") or doc.get("file_unique_id") or "",
                    "file_name": fname,
                    "file_size": doc.get("file_size") or doc.get("size") or 0,
                    "chat_id": doc.get("chat_id"),
                    "message_id": doc.get("message_id") or doc.get("msg_id"),
                    "season": p.get("season"),
                    "episode": p.get("episode"),
                    "quality": p.get("quality") or "UNKNOWN",
                    "languages": p.get("languages") or [],
                })
        except Exception as e:
            logger.debug(f"[SG] scan {cname}: {e}")
            continue
    return all_files


def _summarize_series_files(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group by quality, language, and season."""
    qualities: Set[str] = set()
    languages: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)

    for f in files:
        q = f.get("quality") or "UNKNOWN"
        if q != "UNKNOWN": qualities.add(q)
        for l in (f.get("languages") or []):
            languages.add(l)
        s = f.get("season")
        e = f.get("episode")
        if s is not None:
            if e is not None:
                seasons[s].add(e)
            else:
                seasons[s].add(0)  # season pack

    return {
        "qualities": sorted(qualities, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True),
        "languages": sorted(languages),
        "seasons": {s: sorted(eps) for s, eps in seasons.items()},
        "total_files": len(files),
    }


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_suggestions(items: List[Dict[str, Any]]):
    rows = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?")[:36]
        year = it.get("year") or ""
        label = f"🎬 {title}"
        if year: label += f" ({year})"
        rows.append([InlineKeyboardButton(label,
                                          callback_data=f"sg:pick:{i}")])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_languages(langs: List[str], local_langs: List[str]):
    """Show all TMDB languages; mark which have local files."""
    rows = []
    row = []
    for i, lang in enumerate(langs[:12]):
        has = "🟢" if lang in local_langs else "⚪"
        row.append(InlineKeyboardButton(
            f"{has} {lang}",
            callback_data=f"sg:lang:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_sugg"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_seasons(seasons: List[Dict[str, Any]], local_seasons: Dict[int, List[int]]):
    """Show all seasons; mark which have local files."""
    rows = []
    for i, s in enumerate(seasons[:15]):
        sn = s["season"]
        eps = s.get("episodes", 0)
        local = local_seasons.get(sn, [])
        if local:
            # how many episodes have files
            count = len([e for e in local if e > 0])
            mark = "🟢" if count >= eps else "🟡"
        else:
            count = 0
            mark = "⚪"
        label = f"{mark} S{sn:02d} · {eps} ep"
        if count:
            label += f" · {count} local"
        rows.append([InlineKeyboardButton(label,
                                          callback_data=f"sg:seas:{i}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_lang"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_qualities(qualities: List[str]):
    """Show available qualities (admin-configured or discovered)."""
    rows = []
    row = []
    for i, q in enumerate(qualities[:12]):
        row.append(InlineKeyboardButton(
            f"🎯 {q}",
            callback_data=f"sg:qual:{i}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:back_seas"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def kb_delivering():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⏹️ CANCEL", callback_data="sg:cancel_deliver")]])


def kb_after_deliver(series_title: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📥 SEND AGAIN",
                              callback_data="sg:restart")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")],
    ])


# ═══════════════════════════════════════════════════════════════════════════
# VIEWS
# ═══════════════════════════════════════════════════════════════════════════
def _view_suggestions(raw_query: str, items: List[Dict[str, Any]]) -> str:
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES SEARCH')}</b>",
        DIV, "",
        f"🔍 {sc('you searched')} · <code>{_esc(raw_query)}</code>",
        "",
        f"📌 {sc('pick the series you meant')}",
        "", DIV2, "",
    ]
    for i, it in enumerate(items, 1):
        title = it.get("title") or "?"
        year = it.get("year") or ""
        rating = it.get("rating", 0)
        ov = it.get("overview") or ""
        lines.append(f"<b>{i}.</b> <b>{_esc(title)}</b> ({year}) · ⭐ {rating:.1f}")
        if ov:
            lines.append(f"   <i>{_esc(ov[:100])}...</i>")
        lines.append("")
    return "\n".join(lines)


def _view_languages(series_title: str, series_year: str,
                    langs: List[str], local_langs: List[str]) -> str:
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(series_title)}</b> ({series_year})",
        DIV, "",
        f"🌍 {sc('pick language')}",
        "",
        f"🟢 = ʜᴀᴠᴇ ꜰɪʟᴇꜱ · ⚪ = ᴏɴʟʏ ᴏɴ ᴛᴍᴅʙ",
    ]
    return "\n".join(lines)


def _view_seasons(series_title: str, series_year: str,
                  seasons: List[Dict[str, Any]],
                  local: Dict[int, List[int]]) -> str:
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(series_title)}</b> ({series_year})",
        DIV, "",
        f"📺 {sc('pick season')}",
        "",
        f"🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ɴᴏ ꜰɪʟᴇꜱ",
    ]
    return "\n".join(lines)


def _view_qualities(series_title: str, season: int,
                    qualities: List[str]) -> str:
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(series_title)}</b>",
        f"📺 <b>Season {season:02d}</b>",
        DIV, "",
        f"🎯 {sc('pick quality')}",
        "",
        f"📌 {sc('files will be sent to your pm')}",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# SAFE EDIT
# ═══════════════════════════════════════════════════════════════════════════
async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified: return True
    except Exception as e:
        logger.exception(f"[SG] edit: {e}"); return False


# ═══════════════════════════════════════════════════════════════════════════
# GROUP MESSAGE HANDLER — series search in SERIES_GROUP_ID
# ═══════════════════════════════════════════════════════════════════════════
if SERIES_GROUP_ID:
    @Client.on_message(
        filters.chat(SERIES_GROUP_ID) & filters.text & ~filters.regex(r"^/"),
        group=-420,
    )
    async def series_group_search(client: Client, message: Message):
        """Any text in the series group triggers a series search."""
        try:
            txt = (message.text or "").strip()
            if len(txt) < 2 or len(txt) > 80: return
            if txt.startswith("/"): return
            if "http" in txt.lower(): return
            if not message.from_user: return

            logger.info(f"[SG] search from {message.from_user.id}: {txt!r}")

            # Skip admin commands
            if _is_admin(message.from_user.id) and txt.lower() in \
                    ("caption", "buttons", "prefs", "stats"):
                return

            # TMDB search
            try:
                status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ...")
            except Exception: return

            results = await _tmdb_search_series(txt)

            if not results:
                # No TMDB result — try local only
                await _handle_no_tmdb(client, message, status, txt)
                return

            # Store suggestion list in user session
            _new_session(message.from_user.id,
                         suggestions=results, raw_query=txt)

            text = _view_suggestions(txt, results)
            kb = kb_suggestions(results)

            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=status.id,
                    text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception as e:
                logger.warning(f"[SG] edit suggestions: {e}")

            # Notify in PM
            try:
                await client.send_message(
                    chat_id=message.from_user.id,
                    text="📩 <b>ᴄʜᴇᴄᴋ ᴛʜᴇ ꜱᴇʀɪᴇꜱ ɢʀᴏᴜᴘ</b> — ᴘɪᴄᴋ ʏᴏᴜʀ ꜱʜᴏᴡ!",
                    parse_mode=ParseMode.HTML)
            except Exception: pass

        except Exception as e:
            logger.exception(f"[SG] group search crashed: {e}")


async def _handle_no_tmdb(client, message, status, txt):
    """No TMDB match — try local DB."""
    slug = re.sub(r"[^a-z0-9]+", "_", txt.lower()).strip("_")
    files = await _find_series_files(slug)
    if files:
        await _safe_edit(status,
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
            f"🎬 {sc('found')} · <code>{_esc(txt)}</code>\n"
            f"📁 <code>{len(files)}</code> ꜰɪʟᴇꜱ\n\n"
            f"📌 ᴛʏᴘᴇ ᴛʜᴇ ᴇxᴀᴄᴛ ᴛɪᴛʟᴇ ᴛᴏ ɢᴇᴛ ᴛᴍᴅʙ ᴅᴇᴛᴀɪʟꜱ.")
        return
    await _safe_edit(status,
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
        f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{_esc(txt)}</code>\n\n"
        f"📌 ᴛʀʏ ᴀ ᴅɪꜰꜰᴇʀᴇɴᴛ ꜱᴘᴇʟʟɪɴɢ ᴏʀ ᴛɪᴛʟᴇ.")


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: PICK SERIES SUGGESTION
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:pick:(\d+)$"), group=-420)
async def cb_pick_suggestion(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ · ᴛʀʏ ᴀɢᴀɪɴ", show_alert=True)

        suggestions = s["data"].get("suggestions") or []
        if idx >= len(suggestions):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen = suggestions[idx]
        tmdb_id = chosen.get("tmdb_id")
        title = chosen.get("title") or ""
        year = chosen.get("year") or ""

        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")

        # Fetch full details
        details = await _tmdb_series_details(tmdb_id)
        if not details:
            return await q.answer("⚠️ ᴛᴍᴅʙ ᴇʀʀᴏʀ", show_alert=True)

        # Get languages from TMDB
        tmdb_langs = _tmdb_languages_from_details(details)

        # Get seasons from TMDB
        tmdb_seasons = _tmdb_seasons_from_details(details)

        # Local DB scan for this series
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        local_files = await _find_series_files(slug)
        summary = _summarize_series_files(local_files)

        # Update session
        s["data"]["chosen"] = {
            "tmdb_id": tmdb_id, "title": title, "year": year,
            "poster": chosen.get("poster"),
            "tmdb_langs": tmdb_langs,
            "tmdb_seasons": tmdb_seasons,
            "local_langs": summary["languages"],
            "local_seasons": summary["seasons"],
            "local_qualities": summary["qualities"],
            "local_files": local_files,
        }

        # Move to language step
        await _show_languages(client, q)
    except Exception as e:
        logger.exception(f"[SG] pick_sugg: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


async def _show_languages(client: Client, q: CallbackQuery):
    s = _get_session(q.from_user.id)
    if not s: return
    c = s["data"].get("chosen") or {}
    tmdb_langs = c.get("tmdb_langs") or ["English"]
    local_langs = c.get("local_langs") or []

    # Reorder: languages with local files first, then rest
    ordered = [l for l in tmdb_langs if l in local_langs] + \
              [l for l in tmdb_langs if l not in local_langs]
    c["ordered_langs"] = ordered

    text = _view_languages(c.get("title"), c.get("year"),
                            ordered, local_langs)
    kb = kb_languages(ordered, local_langs)

    poster = _poster_url(c.get("poster"), "w500")
    if poster:
        try:
            await q.message.delete()
        except Exception: pass
        try:
            await client.send_photo(
                chat_id=q.message.chat.id, photo=poster,
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML)
            return
        except Exception: pass
    await _safe_edit(q, text, kb)


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: PICK LANGUAGE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:lang:(\d+)$"), group=-420)
async def cb_pick_language(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        c = s["data"].get("chosen") or {}
        ordered = c.get("ordered_langs") or []
        if idx >= len(ordered):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        lang = ordered[idx]
        c["selected_language"] = lang
        await q.answer(f"🌍 {lang}")

        # Re-filter files for this language
        slug = re.sub(r"[^a-z0-9]+", "_",
                       (c.get("title") or "").lower()).strip("_")
        local_files = await _find_series_files(slug, language=lang)
        c["local_files_lang"] = local_files

        summary = _summarize_series_files(local_files)
        c["seasons_for_lang"] = summary["seasons"]

        # Show seasons
        await _show_seasons(client, q)
    except Exception as e:
        logger.exception(f"[SG] pick_lang: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


async def _show_seasons(client: Client, q: CallbackQuery):
    s = _get_session(q.from_user.id)
    if not s: return
    c = s["data"].get("chosen") or {}
    seasons = c.get("tmdb_seasons") or []
    local_seasons = c.get("seasons_for_lang") or {}

    if not seasons:
        return await q.answer("⚠️ ɴᴏ ꜱᴇᴀꜱᴏɴꜱ ꜰᴏᴜɴᴅ", show_alert=True)

    text = _view_seasons(c.get("title"), c.get("year"),
                          seasons, local_seasons)
    kb = kb_seasons(seasons, local_seasons)
    await _safe_edit(q, text, kb)
    await q.answer()


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: PICK SEASON
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:seas:(\d+)$"), group=-420)
async def cb_pick_season(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        c = s["data"].get("chosen") or {}
        seasons = c.get("tmdb_seasons") or []
        if idx >= len(seasons):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        season = seasons[idx]["season"]
        c["selected_season"] = season
        await q.answer(f"📺 Season {season:02d}")

        # Filter files for language + season
        lang = c.get("selected_language")
        slug = re.sub(r"[^a-z0-9]+", "_",
                       (c.get("title") or "").lower()).strip("_")
        files = await _find_series_files(slug, language=lang, season=season)
        c["local_files_season"] = files

        # Available qualities for this season
        qualities = sorted({f["quality"] for f in files
                            if f.get("quality") not in (None, "UNKNOWN")},
                           key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)

        # Check admin prefs
        pref = await _get_series_pref(slug)
        admin_quals = pref.get("qualities") or []

        if admin_quals:
            # Only show admin-approved qualities that also exist locally
            final_quals = [q for q in admin_quals
                           if q in qualities or not qualities]
            if not final_quals:
                final_quals = admin_quals  # show admin list anyway
        else:
            final_quals = qualities

        c["available_qualities"] = final_quals

        if not final_quals:
            return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ꜱᴇᴀꜱᴏɴ", show_alert=True)

        # Show quality picker
        text = _view_qualities(c.get("title"), season, final_quals)
        kb = kb_qualities(final_quals)
        await _safe_edit(q, text, kb)

    except Exception as e:
        logger.exception(f"[SG] pick_season: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACK: PICK QUALITY → DELIVER EPISODES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:qual:(\d+)$"), group=-420)
async def cb_pick_quality(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        c = s["data"].get("chosen") or {}
        quals = c.get("available_qualities") or []
        if idx >= len(quals):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        quality = quals[idx]
        c["selected_quality"] = quality
        await q.answer(f"🎯 {quality}")

        # Filter files
        files = [f for f in (c.get("local_files_season") or [])
                 if f.get("quality") == quality]

        if not files:
            return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ ᴛʜɪꜱ ǫᴜᴀʟɪᴛʏ",
                                  show_alert=True)

        # Sort by episode
        files.sort(key=lambda x: (x.get("episode") or 0))

        # Update message
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📤 <b>{fb('SENDING EPISODES')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(c.get('title'))}</b>",
            f"📺 <b>Season {c.get('selected_season'):02d}</b>",
            f"🎯 <code>{quality}</code> · 🌍 <code>{c.get('selected_language')}</code>",
            "",
            f"📁 <code>{len(files)}</code> ᴇᴘɪꜱᴏᴅᴇꜱ",
            "",
            f"📩 ꜱᴇɴᴅɪɴɢ ᴛᴏ ʏᴏᴜʀ ᴘᴍ...",
        ])
        kb = kb_delivering()
        await _safe_edit(q, text, kb)

        # Start delivering in the background
        asyncio.create_task(_deliver_episodes(
            client, q.from_user.id, c, files))

    except Exception as e:
        logger.exception(f"[SG] pick_qual: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# EPISODE DELIVERY
# ═══════════════════════════════════════════════════════════════════════════
async def _deliver_episodes(client: Client, user_id: int,
                             chosen: Dict[str, Any],
                             files: List[Dict[str, Any]]):
    """Send each episode to user's PM with clean captions."""
    try:
        # Acknowledge start in PM
        try:
            intro = await client.send_message(
                chat_id=user_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"📤 <b>{fb('DELIVERING')}</b>",
                    DIV, "",
                    f"🎬 <b>{_esc(chosen.get('title'))}</b>",
                    f"📺 Season {chosen.get('selected_season'):02d}",
                    f"🎯 <code>{chosen.get('selected_quality')}</code>",
                    f"🌍 <code>{chosen.get('selected_language')}</code>",
                    "",
                    f"📁 Sending <code>{len(files)}</code> episodes...",
                ]),
                parse_mode=ParseMode.HTML)
        except UserIsBlocked:
            return
        except Exception:
            intro = None

        # Get caption template
        template = await _get_caption()
        extra_buttons = await _get_buttons()
        extra_kb = _build_extra_kb(extra_buttons)

        sent = 0
        failed = 0

        for f in files:
            try:
                ep = f.get("episode")
                size = _fmt_size(f.get("file_size", 0))

                # Build caption
                try:
                    caption = template.format(
                        series=chosen.get("title") or "",
                        season=chosen.get("selected_season") or 0,
                        episode=ep or 0,
                        quality=chosen.get("selected_quality") or "",
                        language=chosen.get("selected_language") or "",
                        size=size,
                    )
                except Exception:
                    caption = (f"🎬 {chosen.get('title')} "
                               f"S{chosen.get('selected_season'):02d}"
                               f"E{ep or 0:02d} · "
                               f"{chosen.get('selected_quality')}")

                # Send the file by copy_message
                src_chat = f.get("chat_id")
                src_msg = f.get("message_id")
                if not (src_chat and src_msg):
                    # No source — try to send by file_id
                    if f.get("file_id"):
                        try:
                            await client.send_cached_media(
                                chat_id=user_id,
                                file_id=f["file_id"],
                                caption=caption,
                                reply_markup=extra_kb,
                                parse_mode=ParseMode.HTML)
                            sent += 1
                        except Exception as e:
                            logger.debug(f"[SG] cached: {e}")
                            failed += 1
                    continue

                try:
                    await client.copy_message(
                        chat_id=user_id,
                        from_chat_id=src_chat,
                        message_id=src_msg,
                        caption=caption,
                        reply_markup=extra_kb,
                        parse_mode=ParseMode.HTML)
                    sent += 1
                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                    try:
                        await client.copy_message(
                            chat_id=user_id,
                            from_chat_id=src_chat,
                            message_id=src_msg,
                            caption=caption,
                            reply_markup=extra_kb,
                            parse_mode=ParseMode.HTML)
                        sent += 1
                    except Exception:
                        failed += 1
                except Exception as e:
                    logger.debug(f"[SG] copy: {e}")
                    failed += 1

                await asyncio.sleep(DELIVER_BATCH_DELAY)

            except Exception as e:
                logger.debug(f"[SG] deliver one: {e}")
                failed += 1

        # Final summary
        try:
            await client.send_message(
                chat_id=user_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"✅ <b>{fb('DONE')}</b>",
                    DIV, "",
                    f"🎬 <b>{_esc(chosen.get('title'))}</b>",
                    f"📺 Season {chosen.get('selected_season'):02d}",
                    "",
                    f"✅ {sc('sent')} · <code>{sent}</code>",
                    f"❌ {sc('failed')} · <code>{failed}</code>",
                    "",
                    f"🕒 {sc('time')} · <code>{_now_ist()}</code>",
                ]),
                parse_mode=ParseMode.HTML)
        except Exception: pass

        logger.info(f"[SG] delivered {sent}/{len(files)} to {user_id}")

    except Exception as e:
        logger.exception(f"[SG] deliver batch: {e}")


def _build_extra_kb(buttons: List[Dict[str, Any]]) -> Optional[InlineKeyboardMarkup]:
    if not buttons: return None
    rows = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if name and url:
            rows.append([InlineKeyboardButton(name[:60], url=url)])
    if not rows: return None
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# BACK / RESTART / CLOSE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:back_sugg$"), group=-420)
async def cb_back_sugg(client: Client, q: CallbackQuery):
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    suggestions = s["data"].get("suggestions") or []
    raw = s["data"].get("raw_query") or ""
    text = _view_suggestions(raw, suggestions)
    kb = kb_suggestions(suggestions)
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_lang$"), group=-420)
async def cb_back_lang(client: Client, q: CallbackQuery):
    await _show_languages(client, q)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_seas$"), group=-420)
async def cb_back_seas(client: Client, q: CallbackQuery):
    await _show_seasons(client, q)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:restart$"), group=-420)
async def cb_restart(client: Client, q: CallbackQuery):
    _clear_session(q.from_user.id)
    try:
        await q.message.edit_text(
            "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🎬 <b>{fb('SERIES SEARCH')}</b>",
                DIV, "",
                f"📌 {sc('type a series name in the group to search')}",
            ]),
            parse_mode=ParseMode.HTML)
    except Exception: pass
    await q.answer("🔄 ꜱᴛᴀʀᴛ ᴀɢᴀɪɴ ɪɴ ᴛʜᴇ ɢʀᴏᴜᴘ")


@Client.on_callback_query(filters.regex(r"^sg:close$"), group=-420)
async def cb_close(client: Client, q: CallbackQuery):
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(filters.regex(r"^sg:cancel_deliver$"), group=-420)
async def cb_cancel_deliver(client: Client, q: CallbackQuery):
    _clear_session(q.from_user.id)
    await q.answer("⏹️ ᴅᴇʟɪᴠᴇʀʏ ᴄᴏɴᴛɪɴᴜᴇꜱ ɪɴ ᴘᴍ", show_alert=True)
    try: await q.message.delete()
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["sgroup", "series_group", "sg"]) & filters.private,
    group=-419,
)
async def cmd_sgroup(client: Client, message: Message):
    """Open series group admin panel."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        _clear_session(message.from_user.id)
        text, kb = await _view_admin_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[SG] /sgroup: {e}")


async def _view_admin_main():
    caption = await _get_caption()
    buttons = await _get_buttons()
    prefs = await _list_series_prefs()

    group_status = (f"<code>{SERIES_GROUP_ID}</code>"
                    if SERIES_GROUP_ID else "⚠️ ɴᴏᴛ ꜱᴇᴛ")

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES GROUP · ADMIN')}</b>",
        DIV, "",
        f"📢 {sc('group id')} · {group_status}",
        f"📝 {sc('caption')} · "
        f"<code>{'custom' if caption != DEFAULT_EPISODE_CAPTION else 'default'}</code>",
        f"🔘 {sc('buttons')} · <code>{len(buttons)}</code>",
        f"🎯 {sc('series prefs')} · <code>{len(prefs)}</code>",
        "",
        DIV2, "",
        f"📌 {sc('user types a name in the group')}",
        f"📌 {sc('bot suggests from tmdb')}",
        f"📌 {sc('user picks language → season → quality')}",
        f"📌 {sc('bot delivers all episodes to pm')}",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 EDIT CAPTION", callback_data="sg:a_caption"),
         InlineKeyboardButton("🔘 MANAGE BUTTONS", callback_data="sg:a_buttons")],
        [InlineKeyboardButton("🎯 SERIES PREFS", callback_data="sg:a_prefs"),
         InlineKeyboardButton("📊 STATS", callback_data="sg:a_stats")],
        [InlineKeyboardButton("📢 SEND TEST", callback_data="sg:a_test")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:a_main$"), group=-419)
async def cb_a_main(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        text, kb = await _view_admin_main()
        await _safe_edit(q, text, kb); await q.answer()
    except Exception as e:
        logger.exception(f"[SG] a_main: {e}")


@Client.on_callback_query(filters.regex(r"^sg:a_close$"), group=-419)
async def cb_a_close(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    try: await q.message.delete()
    except Exception: pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


# ─── CAPTION EDITOR ───
@Client.on_callback_query(filters.regex(r"^sg:a_caption$"), group=-419)
async def cb_a_caption(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        current = await _get_caption()
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📝 <b>{fb('EPISODE CAPTION')}</b>",
            DIV, "",
            f"<b>{sc('current template')}:</b>",
            "",
            f"<code>{_esc(current[:400])}</code>",
            "",
            DIV2, "",
            f"📌 {sc('placeholders')}:",
            f"• <code>{{series}}</code> · ꜱᴇʀɪᴇꜱ ɴᴀᴍᴇ",
            f"• <code>{{season}}</code> · ꜱᴇᴀꜱᴏɴ ɴᴜᴍʙᴇʀ",
            f"• <code>{{episode}}</code> · ᴇᴘɪꜱᴏᴅᴇ ɴᴜᴍʙᴇʀ",
            f"• <code>{{quality}}</code> · ǫᴜᴀʟɪᴛʏ",
            f"• <code>{{language}}</code> · ʟᴀɴɢᴜᴀɢᴇ",
            f"• <code>{{size}}</code> · ꜰɪʟᴇ ꜱɪᴢᴇ",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ EDIT", callback_data="sg:a_cap_edit")],
            [InlineKeyboardButton("♻️ RESET DEFAULT", callback_data="sg:a_cap_reset")],
            [InlineKeyboardButton("👁️ PREVIEW", callback_data="sg:a_cap_prev")],
            [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
             InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
        ])
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] a_caption: {e}")


@Client.on_callback_query(filters.regex(r"^sg:a_cap_edit$"), group=-419)
async def cb_a_cap_edit(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, edit_caption=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption template')}",
        "",
        f"📌 {sc('placeholders')}:",
        f"<code>{{series}}</code> <code>{{season}}</code> <code>{{episode}}</code>",
        f"<code>{{quality}}</code> <code>{{language}}</code> <code>{{size}}</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_caption")]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_cap_reset$"), group=-419)
async def cb_a_cap_reset(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    await _set_caption(DEFAULT_EPISODE_CAPTION)
    await q.answer("♻️ ʀᴇꜱᴇᴛ")
    await cb_a_caption(client, q)


@Client.on_callback_query(filters.regex(r"^sg:a_cap_prev$"), group=-419)
async def cb_a_cap_prev(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    template = await _get_caption()
    try:
        preview = template.format(
            series="Breaking Bad",
            season=1, episode=5,
            quality="1080P", language="English",
            size="1.45 GB")
    except Exception:
        preview = template
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👁️ <b>{fb('CAPTION PREVIEW')}</b>",
        DIV, "", preview,
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data="sg:a_caption")]])
    await _safe_edit(q, text, kb)
    await q.answer()


# ─── BUTTON EDITOR ───
@Client.on_callback_query(filters.regex(r"^sg:a_buttons$"), group=-419)
async def cb_a_buttons(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        buttons = await _get_buttons()
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🔘 <b>{fb('EPISODE BUTTONS')}</b>",
            DIV, "",
        ]
        if not buttons:
            lines.append("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ ʏᴇᴛ.")
            lines.append("")
            lines.append("📌 ᴛʜᴇꜱᴇ ᴀᴘᴘᴇᴀʀ ᴏɴ ᴇᴠᴇʀʏ ᴇᴘɪꜱᴏᴅᴇ ꜱᴇɴᴛ.")
        else:
            for i, b in enumerate(buttons, 1):
                lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
                lines.append(f"   <code>{_esc(b.get('url'))}</code>")
                lines.append("")

        rows = []
        for i, b in enumerate(buttons, 1):
            rows.append([InlineKeyboardButton(
                f"🗑️ {i}. {(b.get('name') or '?')[:30]}",
                callback_data=f"sg:a_btn_rm:{i-1}")])
        rows.append([InlineKeyboardButton("➕ ADD BUTTON",
                                           callback_data="sg:a_btn_add")])
        rows.append([InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
                     InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")])

        await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] a_buttons: {e}")


@Client.on_callback_query(filters.regex(r"^sg:a_btn_add$"), group=-419)
async def cb_a_btn_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, add_button=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send the button in this format')}:",
        "",
        f"<code>Button Name | https://t.me/link</code>",
        "",
        f"📌 {sc('example')}:",
        f"<code>Join Updates | https://t.me/updates</code>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_buttons")]])
    await _safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:a_btn_rm:(\d+)$"), group=-419)
async def cb_a_btn_rm(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    buttons = await _get_buttons()
    if 0 <= idx < len(buttons):
        buttons.pop(idx)
        await _set_buttons(buttons)
    await q.answer("🗑️ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_a_buttons(client, q)


# ─── SERIES PREFS ───
@Client.on_callback_query(filters.regex(r"^sg:a_prefs$"), group=-419)
async def cb_a_prefs(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        prefs = await _list_series_prefs()
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🎯 <b>{fb('SERIES QUALITY PREFS')}</b>",
            DIV, "",
            f"📌 {sc('per-series quality list offered to users')}",
            "",
        ]
        if not prefs:
            lines.append("⚪ ɴᴏ ᴘʀᴇꜰᴇʀᴇɴᴄᴇꜱ ꜱᴇᴛ.")
            lines.append("")
            lines.append("📌 ꜰᴀʟʟʙᴀᴄᴋ = ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇꜱ ꜰᴏᴜɴᴅ ɪɴ ᴅʙ.")
        else:
            for p in prefs[:30]:
                lines.append(f"🎬 <b>{_esc(p.get('title'))}</b>")
                lines.append(f"   🎯 <code>{', '.join(p.get('qualities') or [])}</code>")
                lines.append("")

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ SET SERIES PREFS",
                                   callback_data="sg:a_pref_add")],
            [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_prefs")],
            [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
             InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
        ])
        await _safe_edit(q, "\n".join(lines), kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] a_prefs: {e}")


@Client.on_callback_query(filters.regex(r"^sg:a_pref_add$"), group=-419)
async def cb_a_pref_add(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _new_session(q.from_user.id, pref_add_name=True)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('SET SERIES PREFS')}</b>",
        DIV, "",
        f"📝 {sc('send the series name')}",
        "",
        f"📌 {sc('example')} · <code>Breaking Bad</code>",
        "",
        f"📌 ʙᴏᴛ ᴡɪʟʟ ꜱʜᴏᴡ ᴀᴠᴀɪʟᴀʙʟᴇ ǫᴜᴀʟɪᴛɪᴇꜱ ɪɴ ʏᴏᴜʀ ᴅʙ.",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="sg:a_prefs")]])
    await _safe_edit(q, text, kb)
    await q.answer()


# ─── STATS ───
@Client.on_callback_query(filters.regex(r"^sg:a_stats$"), group=-419)
async def cb_a_stats(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        colls = await _all_file_collections()
        total = 0
        for _, c in colls:
            try: total += await c.estimated_document_count()
            except Exception: pass
        prefs = await _list_series_prefs()
        buttons = await _get_buttons()

        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{fb('SERIES GROUP STATS')}</b>",
            DIV, "",
            f"🗄️ {sc('file collections')} · <code>{len(colls)}</code>",
            f"📁 {sc('total files')} · <code>{_fmt_int(total)}</code>",
            f"🎯 {sc('series prefs')} · <code>{len(prefs)}</code>",
            f"🔘 {sc('buttons')} · <code>{len(buttons)}</code>",
            "",
            f"📢 {sc('group id')} · "
            f"<code>{SERIES_GROUP_ID if SERIES_GROUP_ID else 'not set'}</code>",
            f"🕒 {sc('now')} · <code>{_now_ist()}</code>",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 REFRESH", callback_data="sg:a_stats")],
            [InlineKeyboardButton("◀️ BACK", callback_data="sg:a_main"),
             InlineKeyboardButton("❌ CLOSE", callback_data="sg:a_close")],
        ])
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SG] a_stats: {e}")


# ─── TEST ───
@Client.on_callback_query(filters.regex(r"^sg:a_test$"), group=-419)
async def cb_a_test(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        if not SERIES_GROUP_ID:
            return await q.answer("⚠️ SERIES_GROUP_ID ɴᴏᴛ ꜱᴇᴛ",
                                   show_alert=True)
        await client.send_message(
            chat_id=SERIES_GROUP_ID,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🎬 <b>{fb('SERIES SEARCH READY')}</b>",
                DIV, "",
                f"📌 {sc('type any series name to search')}",
                "",
                f"📌 {sc('example')} · <code>breaking bad</code>",
            ]),
            parse_mode=ParseMode.HTML)
        await q.answer("✅ ꜱᴇɴᴛ ᴛᴏ ɢʀᴏᴜᴘ")
    except Exception as e:
        await q.answer(f"❌ {str(e)[:100]}", show_alert=True)


# ═══════════════════════════════════════════════════════════════════════════
# TEXT INPUT HANDLER — admin edits
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"),
                    group=-418)
async def sg_admin_input(client: Client, message: Message):
    if not message.from_user: return
    if not _is_admin(message.from_user.id): return
    s = _get_session(message.from_user.id)
    if not s: return

    data = s.get("data") or {}
    action = None
    for k in ("edit_caption", "add_button", "pref_add_name"):
        if data.get(k): action = k; break
    if not action: return

    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()

    # ─── EDIT CAPTION ───
    if action == "edit_caption":
        if len(text) < 10:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        ok = await _set_caption(text)
        _clear_session(message.from_user.id)
        await message.reply_text(
            "✅ ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ." if ok else "❌ ꜰᴀɪʟᴇᴅ.",
            parse_mode=ParseMode.HTML)
        return

    # ─── ADD BUTTON ───
    if action == "add_button":
        if "|" not in text:
            return await message.reply_text(
                "❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url:
            return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or
                  url.startswith("https://") or
                  url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        buttons = await _get_buttons()
        if len(buttons) >= 6:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 6 ʙᴜᴛᴛᴏɴꜱ.")
        buttons.append({"name": name[:60], "url": url,
                        "position": len(buttons) + 1})
        await _set_buttons(buttons)
        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ: <b>{_esc(name)}</b>",
            parse_mode=ParseMode.HTML)
        return

    # ─── SET SERIES PREFS — STEP 1: NAME ───
    if action == "pref_add_name":
        # Scan DB for this series
        loading = await message.reply_text("🔍 ꜱᴄᴀɴɴɪɴɢ ᴅʙ...")
        slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        files = await _find_series_files(slug)
        if not files:
            _clear_session(message.from_user.id)
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text=f"❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ <code>{_esc(text)}</code> ɪɴ ᴅʙ.",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        # Collect qualities
        quals = sorted({f.get("quality") for f in files
                        if f.get("quality") not in (None, "UNKNOWN")},
                       key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)

        if not quals:
            _clear_session(message.from_user.id)
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text="⚠️ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ ꜰᴏᴜɴᴅ ɪɴ ꜰɪʟᴇꜱ.",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        # Store in session for the toggle picker
        _new_session(message.from_user.id,
                     pref_working_slug=slug,
                     pref_working_title=text,
                     pref_working_quals=list(quals),
                     pref_working_selected=list(quals))

        # Show picker
        await _show_pref_picker(client, message.chat.id, loading.id)
        return


async def _show_pref_picker(client: Client, chat_id: int, msg_id: int):
    """Render the quality toggle picker for admin prefs."""
    # Find the admin's session
    uid = None
    for u, s in _SESSIONS.items():
        d = s.get("data") or {}
        if d.get("pref_working_slug"):
            uid = u; break
    if uid is None: return

    s = _SESSIONS[uid]
    d = s["data"]
    slug = d.get("pref_working_slug")
    title = d.get("pref_working_title")
    quals = d.get("pref_working_quals") or []
    selected = d.get("pref_working_selected") or []

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('SET SERIES PREFS')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        "",
        f"📌 {sc('pick which qualities to offer')}",
        f"📌 {sc('others will be hidden from users')}",
        "",
        f"✅ {sc('selected')} · <code>{', '.join(selected) or 'none'}</code>",
    ]

    rows = []
    row = []
    for q in quals:
        mark = "✅" if q in selected else "⬜"
        row.append(InlineKeyboardButton(
            f"{mark} {q}",
            callback_data=f"sg:a_pref_tog:{q}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)

    rows.append([InlineKeyboardButton("💾 SAVE",
                                       callback_data="sg:a_pref_save")])
    rows.append([InlineKeyboardButton("❌ CANCEL",
                                       callback_data="sg:a_prefs")])

    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.debug(f"[SG] pref picker: {e}")


@Client.on_callback_query(filters.regex(r"^sg:a_pref_tog:(\w+)$"), group=-419)
async def cb_a_pref_tog(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    qual = q.matches[0].group(1)
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    d = s["data"]
    selected = list(d.get("pref_working_selected") or [])
    if qual in selected: selected.remove(qual)
    else: selected.append(qual)
    d["pref_working_selected"] = selected

    await q.answer("✅" if qual in selected else "⬜")
    await _show_pref_picker(client, q.message.chat.id, q.message.id)


@Client.on_callback_query(filters.regex(r"^sg:a_pref_save$"), group=-419)
async def cb_a_pref_save(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    s = _get_session(q.from_user.id)
    if not s: return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    d = s["data"]
    slug = d.get("pref_working_slug")
    title = d.get("pref_working_title")
    selected = d.get("pref_working_selected") or []

    if not slug:
        return await q.answer("⚠️ ɴᴏ ꜱᴇʀɪᴇꜱ", show_alert=True)

    ok = await _set_series_pref(slug, title, selected)
    _clear_session(q.from_user.id)

    await q.answer("✅ ꜱᴀᴠᴇᴅ" if ok else "❌ ꜰᴀɪʟᴇᴅ")
    # Back to prefs list
    await cb_a_prefs(client, q)


# ═══════════════════════════════════════════════════════════════════════════
# GROUP STARTUP MESSAGE (optional)
# ═══════════════════════════════════════════════════════════════════════════
if SERIES_GROUP_ID:
    @Client.on_message(
        filters.chat(SERIES_GROUP_ID) & filters.command(["start", "help"]),
        group=-420,
    )
    async def series_group_start(client: Client, message: Message):
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"🎬 <b>{fb('SERIES SEARCH')}</b>",
                    DIV, "",
                    f"📌 {sc('type any series name')}",
                    "",
                    f"📌 {sc('examples')}:",
                    f"• <code>breaking bad</code>",
                    f"• <code>game of thrones</code>",
                    f"• <code>the boys</code>",
                    "",
                    DIV2, "",
                    f"🤖 {sc('bot will suggest matches from tmdb')}",
                    f"🌍 {sc('pick language')} → 📺 {sc('season')} → 🎯 {sc('quality')}",
                    f"📩 {sc('files delivered to your pm')}",
                ]),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.id,
                quote=True)
        except Exception as e:
            logger.debug(f"[SG] start: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP + BOOT
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(600)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# FINAL LOG
# ═══════════════════════════════════════════════════════════════════════════
logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  🎬 SERIES GROUP LOADED ✅                                     ║")
logger.info("║                                                                ║")
logger.info("║  Commands (DM, admin):                                         ║")
logger.info("║    /sgroup   — open series group admin panel                   ║")
logger.info("║                                                                ║")
logger.info("║  Env var:                                                      ║")
logger.info("║    SERIES_GROUP_ID=-1001234567890                              ║")
logger.info("║    TMDB_API_KEY=xxx                                            ║")
logger.info("║                                                                ║")
logger.info("║  User flow (in the group):                                     ║")
logger.info("║    1. Type series name                                         ║")
logger.info("║    2. Pick from TMDB suggestions                               ║")
logger.info("║    3. Pick language                                            ║")
logger.info("║    4. Pick season                                              ║")
logger.info("║    5. Pick quality (admin-set or DB-discovered)                ║")
logger.info("║    6. Bot DMs all episodes                                     ║")
logger.info("║                                                                ║")
logger.info("║  Admin (in /sgroup):                                           ║")
logger.info("║    📝 Edit episode caption                                     ║")
logger.info("║    🔘 Manage extra buttons                                     ║")
logger.info("║    🎯 Per-series quality preferences                           ║")
logger.info("║    📊 Stats                                                    ║")
logger.info("║    📢 Send test message to group                               ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")

