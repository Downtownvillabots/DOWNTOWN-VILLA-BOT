# plugins/ai_librarian.py
"""🎛️ AI LIBRARIAN — v2 (sharded + TMDB suggest)"""
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
from pyrogram.errors import MessageNotModified
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

IST = timezone(timedelta(hours=5, minutes=30))
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "").strip()

SESSION_TTL = 900
DAILY_REPORT_HOUR = 9
SERIES_PER_AUTO = 3
PROGRESS_UPDATE_INTERVAL = 2.0

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
    try:
        return db_manager._client or db_manager.client
    except Exception:
        return None


def _completed_coll():
    d = _get_db()
    return d["ai_completed"] if d is not None else None


def _settings_coll():
    d = _get_db()
    return d["ai_settings"] if d is not None else None


def _prefs_coll():
    d = _get_db()
    return d["ai_prefs"] if d is not None else None


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
    try:
        return (await c.find_one({"title_slug": slug})) is not None
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
    try:
        return (await c.delete_one({"title_slug": slug})).deleted_count > 0
    except Exception: return False


async def _list_completed(limit=100):
    c = _completed_coll()
    if c is None: return []
    try:
        return await c.find({}).sort("completed_at", -1).limit(limit).to_list(limit)
    except Exception: return []


async def _count_completed():
    c = _completed_coll()
    if c is None: return 0
    try: return await c.count_documents({})
    except Exception: return 0


async def _delete_file_record(file_id):
    """Delete from ALL file collections."""
    if not file_id: return False
    colls = await _all_file_collections()
    deleted = False
    for _, coll in colls:
        try:
            r = await coll.delete_one({"file_id": file_id})
            if r.deleted_count > 0:
                deleted = True; continue
            r = await coll.delete_one({"file_unique_id": file_id})
            if r.deleted_count > 0: deleted = True
        except Exception:
            continue
    return deleted


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
    try:
        return await c.find({}).sort("updated_at", -1).to_list(200)
    except Exception: return []


async def _all_file_collections():
    """Return [(name, collection), ...] of ALL file-like collections in ALL DBs."""
    results = []
    client = _get_client()

    if client is None:
        d = _get_db()
        if d is not None:
            for n in ("media_files", "files", "media"):
                try:
                    results.append((n, d[n]))
                except Exception: pass
        return results

    try:
        dbs = await client.list_database_names()
    except Exception:
        dbs = []

    patterns = ("media", "file", "shard", "index", "content", "db_", "movie", "series")

    for db_name in dbs:
        if db_name in ("admin", "local", "config"): continue
        try:
            db = client[db_name]
            colls = await db.list_collection_names()
        except Exception:
            continue
        for cname in colls:
            cl = cname.lower()
            if any(p in cl for p in patterns):
                # skip our own collections
                if cname.startswith("ai_"): continue
                try:
                    results.append((f"{db_name}.{cname}", db[cname]))
                except Exception:
                    continue

    # dedupe by collection id
    seen = set()
    unique = []
    for n, c in results:
        try:
            key = str(id(c))
        except Exception:
            key = n
        if key in seen: continue
        seen.add(key)
        unique.append((n, c))
    return unique


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
# PARSER
# ═══════════════════════════════════════════════════════════════════════════
SE_PATTERNS = [
    re.compile(r"[sS](\d{1,2})[\s._-]?[eE][pP]?(\d{1,3})"),
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?[eE]pisode[\s._-]?(\d{1,3})"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?(?:[eE]p|EP)[\s._-]?(\d{1,3})"),
    re.compile(r"[sS](\d{1,2})[\s._-]+[eE](\d{1,3})"),
]
SEASON_ONLY = [
    re.compile(r"\b[sS](\d{1,2})\b(?![\s._-]?[eE])"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})\b(?![\s._-]?[eE])"),
]
YEAR_PATTERN = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")

QUALITY_MARKERS = [
    ("4320p", "4320P"), ("8k", "8K"), ("2160p", "2160P"), ("4k", "4K"),
    ("uhd", "UHD"), ("1440p", "1440P"), ("2k", "2K"), ("1080p", "1080P"),
    ("fullhd", "1080P"), ("fhd", "1080P"), ("720p", "720P"),
    ("576p", "576P"), ("480p", "480P"), ("360p", "360P"),
    ("240p", "240P"), ("hdcam", "HDCAM"), ("cam", "CAM"),
    ("telesync", "TS"), ("ts", "TS"),
]
CODEC_PATTERNS = [
    (re.compile(r"\bav1\b", re.I), "AV1"),
    (re.compile(r"\bx265\b|\bh\.?265\b|\bhevc\b", re.I), "X265"),
    (re.compile(r"\bx264\b|\bh\.?264\b|\bavc\b", re.I), "X264"),
    (re.compile(r"\bmpeg2?\b|\bxvid\b|\bdivx\b", re.I), "MPEG"),
]
SOURCE_PATTERNS = [
    (re.compile(r"\bremux\b", re.I), "REMUX"),
    (re.compile(r"\bbluray\b|\bblu-ray\b|\bbdrip\b|\bbrrip\b|\bbdremux\b", re.I), "BLURAY"),
    (re.compile(r"\bweb-?dl\b|\bwebdl\b|\bamzn\b|\bdsnp\b|\bnf\b|\batvp\b|\bitunes\b|\bpcok\b", re.I), "WEBDL"),
    (re.compile(r"\bweb-?rip\b|\bwebrip\b|\bweb\b", re.I), "WEBRIP"),
    (re.compile(r"\bhdtv\b|\bpdtv\b", re.I), "HDTV"),
    (re.compile(r"\bdvdrip\b|\bdvdscr\b|\bdvd\b|\bhdrip\b", re.I), "DVDRIP"),
    (re.compile(r"\bhdcam\b|\bcam\b", re.I), "CAM"),
    (re.compile(r"\bts\b|\btelesync\b|\btc\b", re.I), "TS"),
    (re.compile(r"\bscreener\b|\bscr\b|\br5\b", re.I), "SCR"),
]
AUDIO_PATTERNS = [
    (re.compile(r"\batmos\b", re.I), "ATMOS"),
    (re.compile(r"\btruehd\b|\bthd\b", re.I), "TRUEHD"),
    (re.compile(r"\bdts-?hd[\s._-]?ma\b|\bdts[\s._-]?hd\b", re.I), "DTS-HD"),
    (re.compile(r"\bdts-?x\b|\bdtsx\b", re.I), "DTSX"),
    (re.compile(r"\bdts\b", re.I), "DTS"),
    (re.compile(r"\bddp[\s._-]?7\.1\b|\bdd\+[\s._-]?7\.1\b", re.I), "DDP7.1"),
    (re.compile(r"\bddp[\s._-]?5\.1\b|\bdd\+[\s._-]?5\.1\b|\beac3\b|\bdd5\.1\b", re.I), "DDP5.1"),
    (re.compile(r"\bddp\b|\bdd\+\b", re.I), "DDP"),
    (re.compile(r"\bac3\b|\bdd\b", re.I), "AC3"),
    (re.compile(r"\baac\b", re.I), "AAC"),
    (re.compile(r"\bflac\b", re.I), "FLAC"),
    (re.compile(r"\bopus\b", re.I), "OPUS"),
    (re.compile(r"\bmp3\b", re.I), "MP3"),
]
SIZE_REGEX = re.compile(r"\b(\d+(?:\.\d+)?)\s*(GB|GiB|MB|MiB)\b", re.IGNORECASE)

LANGUAGE_ALIASES = {
    "English": ["english", "eng"], "Hindi": ["hindi", "hin"],
    "Tamil": ["tamil", "tam"], "Telugu": ["telugu", "tel"],
    "Malayalam": ["malayalam", "mal"], "Kannada": ["kannada", "kan"],
    "Bengali": ["bengali", "bangla"], "Marathi": ["marathi"],
    "Punjabi": ["punjabi"], "Gujarati": ["gujarati"], "Urdu": ["urdu"],
    "Korean": ["korean"], "Japanese": ["japanese"],
    "Chinese": ["chinese", "mandarin"], "Thai": ["thai"],
    "Spanish": ["spanish"], "French": ["french"], "German": ["german"],
    "Italian": ["italian"], "Portuguese": ["portuguese"],
    "Russian": ["russian"], "Turkish": ["turkish"], "Arabic": ["arabic"],
}

NOISE_WORDS = {
    "web", "webdl", "webrip", "bluray", "bdrip", "brrip", "hdtv",
    "x264", "x265", "h264", "h265", "hevc", "avc", "aac", "ac3",
    "dts", "dtshd", "ddp", "dd", "truehd", "atmos", "remux",
    "proper", "repack", "extended", "unrated", "remastered",
    "internal", "dubbed", "dual", "multi", "esubs", "subs",
    "sub", "hdr", "sdr", "dolby", "vision", "imax", "complete",
    "mkv", "mp4", "avi", "mov", "wmv", "flv", "webm",
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


def _parse_size(name):
    m = SIZE_REGEX.search(name)
    if not m: return 0
    try:
        v = float(m.group(1)); u = m.group(2).upper()
        if u in ("GB", "GIB"): return int(v * 1024**3)
        if u in ("MB", "MIB"): return int(v * 1024**2)
    except Exception: pass
    return 0


def _detect(name, patterns):
    for pat, label in patterns:
        if pat.search(name): return label
    return None


def parse_filename(filename):
    result = {"raw": filename, "title": "", "title_slug": "",
              "year": None, "season": None, "episode": None,
              "quality": None, "quality_rank": 0,
              "codec": None, "source": None, "audio_codec": None,
              "languages": [], "size_from_name": 0,
              "is_series": False, "is_season_pack": False}
    if not filename: return result

    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts)$", "",
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
                try:
                    season = int(m.group(1))
                    result["is_season_pack"] = True; break
                except Exception: continue

    result["season"] = season
    result["episode"] = episode

    ym = YEAR_PATTERN.search(work)
    if ym:
        try: result["year"] = int(ym.group(1))
        except Exception: pass

    for marker, label in QUALITY_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", wl):
            result["quality"] = label
            result["quality_rank"] = QUALITY_RANK.get(label, 0); break

    result["codec"] = _detect(wl, CODEC_PATTERNS)
    result["source"] = _detect(wl, SOURCE_PATTERNS)
    result["audio_codec"] = _detect(wl, AUDIO_PATTERNS)

    langs = []
    for ln, aliases in LANGUAGE_ALIASES.items():
        for a in aliases:
            if re.search(r"\b" + re.escape(a) + r"\b", wl):
                if ln not in langs: langs.append(ln)
                break
    result["languages"] = langs
    result["size_from_name"] = _parse_size(name)

    if season is not None or episode is not None:
        result["is_series"] = True

    tw = work
    for pat in SE_PATTERNS: tw = pat.sub(" ", tw)
    for pat in SEASON_ONLY: tw = pat.sub(" ", tw)
    if result["year"]:
        tw = re.sub(r"\b" + str(result["year"]) + r"\b", " ", tw)
    for marker, _ in QUALITY_MARKERS:
        tw = re.sub(r"\b" + re.escape(marker) + r"\b", " ", tw, flags=re.I)
    for lang in langs:
        for a in LANGUAGE_ALIASES.get(lang, []):
            tw = re.sub(r"\b" + re.escape(a) + r"\b", " ", tw, flags=re.I)
    for noise in NOISE_WORDS:
        tw = re.sub(r"\b" + re.escape(noise) + r"\b", " ", tw, flags=re.I)

    # Strip uploader / release group tags
    tw = re.sub(r"[-_.\s]*@\w+\b", " ", tw)
    tw = re.sub(r"[-_.\s]*\[[^\]]{1,40}\]", " ", tw)
    tw = re.sub(r"[-_.\s]*\([^\)]{1,20}\)\s*$", " ", tw)
    tw = re.sub(
        r"[-_.\s]*(?:rarbg|eztv|yts|yify|galaxyrg|psa|hon3y|bolly4u|"
        r"subsplease|evo|fgt|thetvshare|tvshare|hdhub4u|mkvcage|"
        r"shaanig|tamilrockers|isaimini|katmoviehd|moviesverse)\b",
        " ", tw, flags=re.I)

    tw = re.sub(r"[._\-]+", " ", tw)
    tw = re.sub(r"\s+", " ", tw).strip()
    parts = [p for p in tw.split() if len(p) > 1]
    result["title"] = _smart_title_case(" ".join(parts))
    result["title_slug"] = re.sub(r"[^a-z0-9]+", "_",
                                   result["title"].lower()).strip("_")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# SCORING
# ═══════════════════════════════════════════════════════════════════════════
CODEC_BONUS = {"AV1": 10, "X265": 8, "X264": 4, "MPEG": 0, None: 2}
SOURCE_BONUS = {"REMUX": 15, "BLURAY": 12, "WEBDL": 10, "WEBRIP": 7,
                "HDTV": 4, "DVDRIP": 3, "SCR": 2, "CAM": 0, "TS": 0, None: 2}
AUDIO_BONUS = {"ATMOS": 8, "TRUEHD": 7, "DTS-HD": 6, "DTSX": 6, "DTS": 5,
               "DDP7.1": 5, "DDP5.1": 4, "DDP": 3, "AC3": 2, "AAC": 2,
               "FLAC": 5, "OPUS": 2, "MP3": 1, None: 1}


def _score(f):
    res = (f.get("quality") or "UNKNOWN").upper()
    codec = (f.get("codec") or "").upper() or None
    src = (f.get("source") or "").upper() or None
    aud = (f.get("audio_codec") or "").upper() or None
    langs = f.get("languages") or []
    size = f.get("size") or f.get("size_from_name") or 0

    r = QUALITY_RANK.get(res, 25)
    c = CODEC_BONUS.get(codec, 2)
    s = SOURCE_BONUS.get(src, 2)
    a = AUDIO_BONUS.get(aud, 1)
    l = len(langs) * 2
    try:
        size_mb = max(0, size) / (1024**2)
        sz = min(20.0, size_mb / 500.0)
    except Exception:
        sz = 0.0
    return round(r + c + s + a + l + sz, 1)


def _pick_best(files):
    if not files: return None, []
    scored = sorted([(_score(f), f) for f in files], key=lambda x: x[0], reverse=True)
    if all((f.get("quality") or "UNKNOWN").upper() == "UNKNOWN" for _, f in scored):
        return None, []
    best = scored[0][1]; best["_score"] = scored[0][0]
    others = []
    for s, f in scored[1:]:
        f["_score"] = s; others.append(f)
    return best, others


# ═══════════════════════════════════════════════════════════════════════════
# CATALOG
# ═══════════════════════════════════════════════════════════════════════════
class SeriesCatalog:
    def __init__(self):
        self.data: Dict[str, Any] = {}

    def add(self, parsed, rec):
        if not parsed.get("is_series"): return
        if parsed.get("season") is None: return
        slug = parsed["title_slug"]
        if not slug: return

        if slug not in self.data:
            self.data[slug] = {"title": parsed["title"],
                                "seasons": defaultdict(lambda: defaultdict(list)),
                                "file_count": 0}

        s = parsed["season"]; e = parsed.get("episode")
        size = (rec.get("file_size") or rec.get("size")
                or parsed.get("size_from_name") or 0)

        self.data[slug]["seasons"][s][e].append({
            "file_id": rec.get("file_id") or rec.get("file_unique_id") or "",
            "file_name": parsed.get("raw", ""),
            "quality": (parsed.get("quality") or "UNKNOWN").upper(),
            "codec": (parsed.get("codec") or "").upper() or None,
            "source": (parsed.get("source") or "").upper() or None,
            "audio_codec": (parsed.get("audio_codec") or "").upper() or None,
            "languages": parsed.get("languages", []),
            "size": size,
            "size_from_name": parsed.get("size_from_name", 0),
            "chat_id": rec.get("chat_id"),
            "message_id": rec.get("message_id") or rec.get("msg_id"),
            "_score": 0,
        })
        self.data[slug]["file_count"] += 1

    def list_series(self):
        out = [{"title_slug": k, "title": v["title"],
                "file_count": v["file_count"],
                "season_count": len(v["seasons"])} for k, v in self.data.items()]
        out.sort(key=lambda x: x["title"].lower())
        return out


# ═══════════════════════════════════════════════════════════════════════════
# TMDB SUGGEST
# ═══════════════════════════════════════════════════════════════════════════
async def _tmdb_suggest(query: str, kind: str = "tv") -> List[Dict[str, Any]]:
    """Search TMDB for TV shows (or movies) matching query."""
    if not TMDB_API_KEY: return []
    try:
        import aiohttp
    except ImportError:
        return []

    endpoint = "/search/tv" if kind == "tv" else "/search/movie"
    params = {"api_key": TMDB_API_KEY, "query": query, "language": "en-US"}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://api.themoviedb.org/3{endpoint}",
                                params=params, timeout=12) as r:
                if r.status != 200: return []
                data = await r.json()
    except Exception as e:
        logger.debug(f"[AI] tmdb suggest: {e}")
        return []

    out = []
    for it in (data.get("results") or [])[:8]:
        if kind == "tv":
            title = it.get("name") or it.get("original_name") or ""
            date = it.get("first_air_date") or ""
        else:
            title = it.get("title") or it.get("original_title") or ""
            date = it.get("release_date") or ""
        if not title: continue
        out.append({
            "title": title,
            "year": (date or "")[:4],
            "tmdb_id": it.get("id"),
            "overview": (it.get("overview") or "")[:150],
            "rating": it.get("vote_average", 0),
            "poster": it.get("poster_path"),
            "type": kind,
        })
    return out


def _tmdb_poster(path):
    return f"https://image.tmdb.org/t/p/w200{path}" if path else None


def kb_tmdb_suggest(items: List[Dict[str, Any]]):
    rows = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?")[:38]
        year = it.get("year") or ""
        label = f"🎬 {title}"
        if year: label += f" ({year})"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"ai:pick_tmdb:{i}")])
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


def kb_scan_result(slug, i, t):
    rows = [
        [InlineKeyboardButton("👁️ VIEW FILES", callback_data=f"ai:view:{slug}")],
        [InlineKeyboardButton("🎯 SET KEEP QUALITIES", callback_data=f"ai:pref:{slug}")],
        [InlineKeyboardButton("✅ MARK COMPLETE", callback_data=f"ai:complete:{slug}")],
    ]
    if i < t:
        rows.append([InlineKeyboardButton(f"⏭️ NEXT ({i+1}/{t})",
                                           callback_data=f"ai:next:{slug}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_series_list(lst):
    rows = [[InlineKeyboardButton(f"🎬 {(s.get('title') or '?')[:32]} · {s.get('file_count', 0)}",
                                   callback_data=f"ai:view:{s['title_slug']}")]
            for s in lst[:25]]
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_episode_files(slug, season, episode, files):
    rows = []
    for i, f in enumerate(files[:10]):
        q = f.get("quality", "?")
        langs = "+".join(f.get("languages", [])) or "?"
        ep_i = episode if episode is not None else 0
        rows.append([InlineKeyboardButton(f"🗑️ {i+1}. {q} · {langs}",
            callback_data=f"ai:del_pick:{slug}:{season}:{ep_i}:{i}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data=f"ai:view:{slug}"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_delete(slug, season, episode, idx):
    ep_i = episode if episode is not None else 0
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, DELETE",
            callback_data=f"ai:del_go:{slug}:{season}:{ep_i}:{idx}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"ai:view:{slug}")],
    ])


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
# VIEWS
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
        f"✍️ {sc('manual')} · ꜱᴇᴀʀᴄʜ ᴏɴᴇ (ᴛᴍᴅʙ ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ)",
        "", DIV2,
        f"🕒 <code>{_now_ist()}</code>",
    ]), kb_main(auto_on, comp, total)


def _progress_bar(p, w=16):
    p = max(0.0, min(100.0, float(p)))
    filled = int(w * p / 100); empty = w - filled
    block = "🟩" if p >= 75 else ("🟨" if p >= 50 else ("🟧" if p >= 25 else "🟥"))
    return block * filled + "⬛" * empty + f"  {p:.0f}%"


def _view_scanning(cur, total, coll=""):
    p = (cur / total * 100) if total else 0
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('SCANNING')}</b>",
        DIV, "",
        f"<code>{_progress_bar(p)}</code>",
        "",
        f"📁 <code>{_fmt_int(cur)}</code> / <code>{_fmt_int(total)}</code>",
    ]
    if coll: lines.append(f"📚 <code>{_esc(coll[:40])}</code>")
    return "\n".join(lines)


def _view_series_result(series, prefs, i, t):
    title = series.get("title") or "?"
    seasons = series.get("seasons") or {}
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🎬 <b>{_esc(title)}</b>",
             f"📄 {sc('series')} · <code>{i}/{t}</code>",
             DIV, ""]
    total_files = 0
    for sn in sorted(seasons.keys()):
        eps = seasons[sn]
        lines.append(f"📺 <b>{sc('season')} {sn}</b> · <code>{len(eps)} ᴇᴘɪꜱᴏᴅᴇꜱ</code>")
        qmap = defaultdict(set)
        for ep, files in eps.items():
            for f in files:
                qmap[f.get("quality", "?")].add(ep if ep is not None else 0)
                total_files += 1
        for q in sorted(qmap.keys(), key=lambda x: QUALITY_RANK.get(x, 0), reverse=True):
            eps_p = sorted(qmap[q])
            ps = ", ".join(f"E{e:02d}" if e else "?" for e in eps_p[:15])
            if len(eps_p) > 15: ps += f" +{len(eps_p) - 15}"
            mk = ""
            if prefs and q not in prefs: mk = " · 🗑️ ᴛᴏ ᴅᴇʟᴇᴛᴇ"
            elif prefs and q in prefs: mk = " · ✅ ᴋᴇᴇᴘ"
            lines.append(f"   🎯 <code>{q}</code> · <code>{ps}</code>{mk}")
        lines.append("")
    lines.append(DIV2)
    lines.append(f"📁 {sc('total files')} · <code>{_fmt_int(total_files)}</code>")
    if prefs:
        lines.append(f"🎯 {sc('keep')} · <code>{', '.join(prefs)}</code>")
    return "\n".join(lines)


def _view_episode_files(title, season, episode, files, prefs):
    ep = f"S{season:02d}" + (f"E{episode:02d}" if episode else "")
    best, _ = _pick_best(files)
    lines = [f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
             f"🎬 <b>{_esc(title)}</b> · <code>{ep}</code>",
             DIV, "",
             f"📁 <code>{len(files)}</code> ꜰɪʟᴇꜱ",
             ""]
    for i, f in enumerate(files[:10]):
        q = f.get("quality", "?")
        langs = "+".join(f.get("languages", [])) or "?"
        size = _fmt_size(f.get("size", 0) or f.get("size_from_name", 0))
        codec = f.get("codec") or "?"
        src = f.get("source") or "?"
        tag = ""
        if f is best: tag = " · ⭐ ʙᴇꜱᴛ"
        elif prefs and q not in prefs: tag = " · 🗑️ ʀᴇᴍᴏᴠᴇ"
        elif q == "UNKNOWN": tag = " · ⚠️ ᴜɴᴋɴᴏᴡɴ"
        lines.append(f"<b>{i+1}.</b> <code>{q}</code> · <code>{codec}</code> · <code>{src}</code>{tag}")
        lines.append(f"   🌍 <code>{langs}</code> · 📦 {size}")
    lines += ["", DIV2, f"📌 {sc('tap a file to delete it')}"]
    return "\n".join(lines)


def _view_confirm_delete(title, season, episode, f):
    ep = f"S{season:02d}" + (f"E{episode:02d}" if episode else "")
    q = f.get("quality", "?"); langs = "+".join(f.get("languages", [])) or "?"
    size = _fmt_size(f.get("size", 0) or f.get("size_from_name", 0))
    return "\n".join([
        f"⚠️ <b>{fb('CONFIRM DELETE')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b> · <code>{ep}</code>",
        f"🎯 {sc('quality')} · <code>{q}</code>",
        f"🌍 {sc('languages')} · <code>{langs}</code>",
        f"📦 {sc('size')} · <code>{size}</code>",
        "", DIV2, f"❗ <b>{sc('this cannot be undone')}</b>",
    ])


def _view_quality_picker(title, avail, cur):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('QUALITY PREFERENCES')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        "",
        f"📊 {sc('found')} · <code>{', '.join(avail) or 'none'}</code>",
        f"✅ {sc('keeping')} · <code>{', '.join(cur) or 'none'}</code>",
    ])


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
# SCAN LIBRARY — ALL COLLECTIONS
# ═══════════════════════════════════════════════════════════════════════════
async def _scan_library(client, chat_id, status_msg_id, filter_slug=None):
    colls = await _all_file_collections()
    if not colls:
        logger.warning("[AI] no file collections")
        return SeriesCatalog()

    total = 0; counts = {}
    for name, c in colls:
        try:
            n = await c.estimated_document_count()
            counts[name] = n; total += n
        except Exception: counts[name] = 0

    logger.info(f"[AI] scanning {len(colls)} colls, {total} docs")

    cat = SeriesCatalog()
    processed = 0
    last_edit = 0.0

    for cname, coll in colls:
        try:
            async for doc in coll.find({}):
                processed += 1
                fname = (doc.get("file_name") or doc.get("filename")
                         or doc.get("title") or doc.get("name")
                         or doc.get("file_title") or doc.get("caption")
                         or doc.get("file_caption") or doc.get("media_title")
                         or doc.get("text") or "")
                if not fname:
                    for k, v in doc.items():
                        if k in ("_id","chat_id","message_id","msg_id",
                                 "file_id","file_unique_id","file_size","size"):
                            continue
                        if isinstance(v, str) and len(v) > 5:
                            if any(x in v.lower() for x in
                                   (".mkv",".mp4",".avi",".mov",".webm",".ts",".m4v")):
                                fname = v; break
                if not fname: continue

                p = parse_filename(str(fname))
                if filter_slug is not None:
                    sm = p.get("title_slug", "")
                    if filter_slug not in sm and sm not in filter_slug:
                        continue

                cat.add(p, doc)

                now = time.time()
                if now - last_edit >= PROGRESS_UPDATE_INTERVAL:
                    last_edit = now
                    try:
                        await client.edit_message_text(
                            chat_id=chat_id, message_id=status_msg_id,
                            text=_view_scanning(processed, total, cname),
                            parse_mode=ParseMode.HTML)
                    except Exception: pass
        except Exception as e:
            logger.warning(f"[AI] scan {cname}: {e}"); continue

    logger.info(f"[AI] done: {processed} files, {len(cat.data)} series")
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=status_msg_id,
            text=_view_scanning(processed, total),
            parse_mode=ParseMode.HTML)
    except Exception: pass
    return cat


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
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[AI] /ai: {e}")


@Client.on_message(filters.command(["aidb", "aishards"]) & filters.private, group=-430)
async def cmd_aidb(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        colls = await _all_file_collections()
        lines = ["🗄️ <b>ᴍᴏɴɢᴏ ᴅɪᴀɢɴᴏꜱᴛɪᴄꜱ</b>",
                 "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                 f"📁 <b>{len(colls)} ꜰɪʟᴇ ᴄᴏʟʟᴇᴄᴛɪᴏɴꜱ ꜰᴏᴜɴᴅ</b>", ""]
        for name, c in colls:
            try: n = await c.estimated_document_count()
            except Exception: n = -1
            lines.append(f"• <code>{_esc(name[:60])}</code> · {_fmt_int(n)}")
        # sample
        if colls:
            try:
                sample = await colls[0][1].find_one({})
                if sample:
                    sample.pop("_id", None)
                    lines += ["", "🔑 <b>ꜱᴀᴍᴘʟᴇ ꜰɪᴇʟᴅꜱ</b>"]
                    for k in list(sample.keys())[:25]:
                        v = str(sample[k])[:70]
                        lines.append(f"• <code>{k}</code> = {_esc(v)}")
            except Exception: pass
        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception(f"[AI] /aidb: {e}")
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
async def cb_toggle_auto(client, q):
    cur = await _get_setting("auto_mode", True)
    await _set_setting("auto_mode", not cur)
    await q.answer("🟢 ᴀᴜᴛᴏ ᴏɴ" if not cur else "🔴 ᴀᴜᴛᴏ ᴏꜰꜰ")
    text, kb = await _view_main()
    await _safe_edit(q, text, kb)


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
        except Exception:
            status = q.message

        cat = await _scan_library(client, q.message.chat.id, status.id)
        if cat is None:
            return await client.edit_message_text(
                chat_id=q.message.chat.id, message_id=status.id,
                text="⚠️ ᴅʙ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ.", parse_mode=ParseMode.HTML)

        all_s = cat.list_series()
        await _set_setting("total_series", len(all_s))

        pending = [s for s in all_s
                   if not await _is_completed(s["title_slug"])]

        if not pending:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=status.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"✅ <b>{fb('ALL REVIEWED')}</b>",
                        DIV, "",
                        f"🎉 {sc('every series is completed')}",
                        f"📊 {sc('total')} · <code>{len(all_s)}</code>",
                    ]),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")]]),
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
        logger.exception(f"[AI] cb_auto: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# MANUAL SCAN — with TMDB SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:manual$"), group=-430)
async def cb_manual(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    _clear_session(q.from_user.id)
    _new_session(q.from_user.id, "manual_name")
    await _safe_edit(q, "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✍️ <b>{fb('MANUAL SCAN')}</b>",
        DIV, "",
        f"📝 {sc('send a name or short form')}",
        "",
        f"📌 {sc('examples')}:",
        f"• <code>got</code>",
        f"• <code>game of thrones</code>",
        f"• <code>breaking bad</code>",
        "",
        f"💡 {sc('bot will suggest from tmdb')}",
    ]), InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")]]))
    await q.answer()


@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"), group=-429)
async def ai_manual_input(client, message):
    if not message.from_user: return
    s = _get_session(message.from_user.id)
    if not s or s["action"] not in ("manual_name", "manual_tmdb"):
        return
    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()
    if len(text) < 2:
        return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")

    _clear_session(message.from_user.id)

    # Ask TMDB
    try:
        loading = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ ᴛᴍᴅʙ...")
    except Exception:
        return

    suggestions = await _tmdb_suggest(text, kind="tv")

    if not suggestions:
        # No TMDB → try local scan directly
        try:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=loading.id,
                text="🔍 ᴛᴍᴅʙ ɴᴏ ʀᴇꜱᴜʟᴛꜱ · ꜱᴄᴀɴɴɪɴɢ ᴅʙ ʟᴏᴄᴀʟʟʏ...",
                parse_mode=ParseMode.HTML)
        except Exception: pass

        slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
        cat = await _scan_library(client, message.chat.id, loading.id,
                                    filter_slug=slug)
        if cat is None or not cat.data:
            try:
                await client.edit_message_text(
                    chat_id=message.chat.id, message_id=loading.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"❌ <b>{fb('NOT FOUND')}</b>",
                        DIV, "",
                        f"🔍 <code>{_esc(text)}</code>",
                        f"📌 {sc('not in your db')}",
                    ]),
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

    # Cache suggestions in session
    _new_session(message.from_user.id, "manual_tmdb_pick",
                 suggestions=suggestions, query=text)

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔎 <b>{fb('TMDB SUGGESTIONS')}</b>",
        DIV, "",
        f"📝 {sc('you searched')} · <code>{_esc(text)}</code>",
        "",
        f"📌 {sc('tap a title to scan your db')}",
        "",
        DIV2, "",
    ]
    for i, it in enumerate(suggestions, 1):
        title = it.get("title") or "?"
        yr = it.get("year") or ""
        rating = it.get("rating", 0)
        lines.append(f"<b>{i}.</b> <b>{_esc(title)}</b> ({yr})")
        if rating:
            lines.append(f"   ⭐ <code>{rating:.1f}</code>")
        lines.append("")

    try:
        await client.edit_message_text(
            chat_id=message.chat.id, message_id=loading.id,
            text="\n".join(lines),
            reply_markup=kb_tmdb_suggest(suggestions),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.warning(f"[AI] tmdb suggest: {e}")


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

        await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ ᴅʙ...")
        try:
            await q.message.edit_text(_view_scanning(0, 0),
                                       parse_mode=ParseMode.HTML)
        except Exception: pass

        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        cat = await _scan_library(client, q.message.chat.id, q.message.id,
                                    filter_slug=slug)

        if cat is None or not cat.data:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=q.message.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"❌ <b>{fb('NOT IN YOUR DB')}</b>",
                        DIV, "",
                        f"🎬 <b>{_esc(title)}</b>",
                        f"📅 <code>{chosen.get('year') or '?'}</code>",
                        "",
                        DIV2, "",
                        f"📌 {sc('this series is not in your library')}",
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

        _new_session(q.from_user.id, "manual_result")
        sess = _SESSIONS[q.from_user.id]
        sess["catalog_data"] = cat.data

        # Find best slug match
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
    text = _view_series_result(
        {"title": series.get("title"), "seasons": series.get("seasons")},
        prefs, i, t)
    kb = kb_scan_result(slug, i, t)

    sess["current_slug"] = slug
    sess["current_index"] = i
    sess["current_total"] = t

    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)
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
# VIEW FILES / QUALITY PREFS / COMPLETE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:view:([a-z0-9_]+)$"), group=-430)
async def cb_view(client, q):
    try:
        slug = q.matches[0].group(1)
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        seasons = series.get("seasons") or {}
        if not seasons: return await q.answer("⚠️ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)
        fs = sorted(seasons.keys())[0]
        eps = seasons[fs]
        fe = sorted([e for e in eps.keys() if e is not None])[0] \
            if any(e is not None for e in eps.keys()) else None
        if fe is None: return await q.answer("⚠️ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)
        files = eps[fe]
        for f in files: f["_score"] = _score(f)
        prefs = await _get_prefs(slug)
        await _safe_edit(q,
            _view_episode_files(series.get("title"), fs, fe, files, prefs),
            kb_episode_files(slug, fs, fe, files))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] view: {e}")


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
            for _, files in eps.items():
                for f in files:
                    if f.get("quality"): avail.add(f["quality"])
        al = sorted(avail, key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
        if not al: return await q.answer("⚠️ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ", show_alert=True)
        cur = await _get_prefs(slug)
        s["pref_working"] = list(cur)
        await _safe_edit(q, _view_quality_picker(series.get("title"), al, cur),
                          kb_quality_picker(slug, al, cur))
        await q.answer()
    except Exception as e: logger.exception(f"[AI] pref: {e}")


@Client.on_callback_query(filters.regex(r"^ai:pref_tog:([a-z0-9_]+):(\w+)$"), group=-430)
async def cb_pref_tog(client, q):
    try:
        slug = q.matches[0].group(1); qual = q.matches[0].group(2)
        s = _get_session(q.from_user.id)
        if not s: return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        w = s.get("pref_working") or []
        w.remove(qual) if qual in w else w.append(qual)
        s["pref_working"] = w
        series = (s.get("catalog_data") or {}).get(slug) or {}
        avail = set()
        for _, eps in (series.get("seasons") or {}).items():
            for _, files in eps.items():
                for f in files:
                    if f.get("quality"): avail.add(f["quality"])
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
        await _safe_edit(q,
            _view_series_result({"title": title, "seasons": series.get("seasons")},
                                w, s.get("current_index", 1), s.get("current_total", 1)),
            kb_scan_result(slug, s.get("current_index", 1), s.get("current_total", 1)))
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
            f"✅ <b>{fb('MARKED COMPLETE')}</b>",
            DIV, "",
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
        cat = await _scan_library(client, q.message.chat.id, status.id)
        if cat is None: return
        all_s = cat.list_series()
        await _set_setting("total_series", len(all_s))
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
                 f"📚 <b>{fb('ALL SERIES')}</b>",
                 DIV, "",
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
# DELETE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:del_pick:([a-z0-9_]+):(\d+):(\d+):(\d+)$"), group=-430)
async def cb_del_pick(client, q):
    try:
        slug = q.matches[0].group(1)
        sn = int(q.matches[0].group(2))
        ep_raw = int(q.matches[0].group(3))
        idx = int(q.matches[0].group(4))
        ep = ep_raw if ep_raw > 0 else None
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        files = ((series.get("seasons") or {}).get(sn) or {}).get(ep, [])
        if idx < 0 or idx >= len(files):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        await _safe_edit(q, _view_confirm_delete(series.get("title"), sn, ep, files[idx]),
                          kb_confirm_delete(slug, sn, ep, idx))
        await q.answer()
    except Exception as e: logger.exception(f"[AI] del_pick: {e}")


@Client.on_callback_query(filters.regex(r"^ai:del_go:([a-z0-9_]+):(\d+):(\d+):(\d+)$"), group=-430)
async def cb_del_go(client, q):
    try:
        slug = q.matches[0].group(1)
        sn = int(q.matches[0].group(2))
        ep_raw = int(q.matches[0].group(3))
        idx = int(q.matches[0].group(4))
        ep = ep_raw if ep_raw > 0 else None
        s = _get_session(q.from_user.id)
        if not s or not s.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        series = s["catalog_data"].get(slug)
        if not series: return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        files = ((series.get("seasons") or {}).get(sn) or {}).get(ep, [])
        if idx < 0 or idx >= len(files):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)
        fid = files[idx].get("file_id") or ""
        if not fid: return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇ ɪᴅ", show_alert=True)
        ok = await _delete_file_record(fid)
        if not ok: return await q.answer("❌ ᴅᴇʟᴇᴛᴇ ꜰᴀɪʟᴇᴅ", show_alert=True)
        files.pop(idx)
        s["catalog_data"][slug]["seasons"][sn][ep] = files
        await q.answer("🗑️ ᴅᴇʟᴇᴛᴇᴅ")
        for f in files: f["_score"] = _score(f)
        prefs = await _get_prefs(slug)
        await _safe_edit(q,
            _view_episode_files(series.get("title"), sn, ep, files, prefs),
            kb_episode_files(slug, sn, ep, files))
    except Exception as e: logger.exception(f"[AI] del_go: {e}")


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
            f"🎛️ <b>{fb('DAILY AI REPORT')}</b>",
            DIV, "",
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
            f"", f"🕒 <code>{_now_ist()}</code>"]), kb_back("ai:main"))
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


logger.info("🎛️ AI LIBRARIAN v2 LOADED — sharded scan + TMDB suggest")
