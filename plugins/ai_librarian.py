# plugins/ai_librarian.py
"""
🎛️ DOWNTOWN VILLA — AI LIBRARIAN

Scans media_files DB, groups series by season/episode/quality,
scores files, suggests duplicates, tracks completed series.
"""
# ═══════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════
import asyncio
import logging
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

SESSION_TTL = 900
DAILY_REPORT_HOUR = 9
DAILY_REPORT_MINUTE = 0
SERIES_PER_AUTO = 3
PROGRESS_UPDATE_INTERVAL = 2.0

DIV = "━" * 26
DIV2 = "─" * 26

QUALITY_RANK = {
    "4320P": 100, "8K": 100,
    "2160P": 90, "4K": 90, "UHD": 90,
    "1440P": 80, "2K": 80,
    "1080P": 70, "FULLHD": 70, "FHD": 70,
    "720P": 60, "HD": 60,
    "576P": 50,
    "480P": 40, "SD": 40,
    "360P": 30,
    "240P": 20,
    "CAM": 5, "HDCAM": 5, "TS": 3, "TELESYNC": 3,
    "UNKNOWN": 25,
}

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

def _fmt_size(bytes_) -> str:
    if not bytes_: return "0 B"
    try: s = float(bytes_)
    except (TypeError, ValueError): return "0 B"
    for u in ["B", "KB", "MB", "GB", "TB"]:
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
# DB HELPERS
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


def _files_coll():
    d = _get_db()
    if d is None: return None
    for name in ("media_files", "files", "media"):
        try:
            c = d[name]
            if c is not None: return c
        except Exception: pass
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


async def _get_setting(key: str, default: Any = None) -> Any:
    c = _settings_coll()
    if c is None: return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception:
        return default


async def _set_setting(key: str, value: Any) -> bool:
    c = _settings_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {key: value, "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception:
        return False


async def _is_completed(title_slug: str) -> bool:
    c = _completed_coll()
    if c is None: return False
    try:
        doc = await c.find_one({"title_slug": title_slug})
        return doc is not None
    except Exception:
        return False


async def _mark_completed(title: str, title_slug: str,
                          total_files: int) -> bool:
    c = _completed_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"title_slug": title_slug},
            {"$set": {
                "title": title, "title_slug": title_slug,
                "total_files": total_files,
                "completed_at": time.time(),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def _unmark_completed(title_slug: str) -> bool:
    c = _completed_coll()
    if c is None: return False
    try:
        r = await c.delete_one({"title_slug": title_slug})
        return r.deleted_count > 0
    except Exception:
        return False


async def _list_completed(limit: int = 100) -> List[Dict[str, Any]]:
    c = _completed_coll()
    if c is None: return []
    try:
        cursor = c.find({}).sort("completed_at", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []


async def _count_completed() -> int:
    c = _completed_coll()
    if c is None: return 0
    try: return await c.count_documents({})
    except Exception: return 0


async def _delete_file_record(file_id: str) -> bool:
    c = _files_coll()
    if c is None: return False
    try:
        r = await c.delete_one({"file_id": file_id})
        if r.deleted_count == 0:
            r = await c.delete_one({"file_unique_id": file_id})
        return r.deleted_count > 0
    except Exception:
        return False


async def _get_prefs(title_slug: str) -> List[str]:
    c = _prefs_coll()
    if c is None: return []
    try:
        doc = await c.find_one({"title_slug": title_slug})
        if not doc: return []
        return list(doc.get("keep_qualities") or [])
    except Exception:
        return []


async def _set_prefs(title_slug: str, title: str, qualities: List[str]) -> bool:
    c = _prefs_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"title_slug": title_slug},
            {"$set": {
                "title_slug": title_slug, "title": title,
                "keep_qualities": list(qualities),
                "updated_at": time.time(),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def _list_prefs() -> List[Dict[str, Any]]:
    c = _prefs_coll()
    if c is None: return []
    try:
        cursor = c.find({}).sort("updated_at", -1)
        return await cursor.to_list(length=200)
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SESSIONS
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}

def _new_session(uid: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[uid] = {"token": tok, "action": action, "data": data,
                      "expires": time.time() + SESSION_TTL}
    return tok

def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(uid, None); return None
    return s

def _clear_session(uid: int) -> None:
    _SESSIONS.pop(uid, None)

def _cleanup_sessions() -> None:
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now: _SESSIONS.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════
# AI FILENAME PARSER (with uploader-tag stripping)
# ═══════════════════════════════════════════════════════════════════════════
SE_PATTERNS = [
    re.compile(r"[sS](\d{1,2})[\s._-]?[eE][pP]?(\d{1,3})"),
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?[eE]pisode[\s._-]?(\d{1,3})"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?(?:[eE]p|EP)[\s._-]?(\d{1,3})"),
    re.compile(r"[sS](\d{1,2})[\s._-]+[eE](\d{1,3})"),
]

SEASON_ONLY_PATTERNS = [
    re.compile(r"\b[sS](\d{1,2})\b(?![\s._-]?[eE])"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})\b(?![\s._-]?[eE])"),
]

YEAR_PATTERN = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")

QUALITY_MARKERS = [
    ("4320p", "4320P"), ("8k", "8K"),
    ("2160p", "2160P"), ("4k", "4K"), ("uhd", "UHD"),
    ("1440p", "1440P"), ("2k", "2K"),
    ("1080p", "1080P"), ("fullhd", "1080P"), ("fhd", "1080P"),
    ("720p", "720P"),
    ("576p", "576P"),
    ("480p", "480P"),
    ("360p", "360P"),
    ("240p", "240P"),
    ("hdcam", "HDCAM"), ("cam", "CAM"),
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
    (re.compile(r"\bddp[\s._-]?7\.1\b|\bdd\+[\s._-]?7\.1\b|\beac3[\s._-]?7\.1\b", re.I), "DDP7.1"),
    (re.compile(r"\bddp[\s._-]?5\.1\b|\bdd\+[\s._-]?5\.1\b|\beac3\b|\bdd5\.1\b", re.I), "DDP5.1"),
    (re.compile(r"\bddp\b|\bdd\+\b", re.I), "DDP"),
    (re.compile(r"\bac3\b|\bdd\b", re.I), "AC3"),
    (re.compile(r"\baac\b", re.I), "AAC"),
    (re.compile(r"\bflac\b", re.I), "FLAC"),
    (re.compile(r"\bopus\b", re.I), "OPUS"),
    (re.compile(r"\bmp3\b", re.I), "MP3"),
]

SIZE_REGEX = re.compile(r"\b(\d+(?:\.\d+)?)\s*(GB|GiB|MB|MiB)\b", re.IGNORECASE)

MULTI_AUDIO_MARKERS = [
    re.compile(r"\bmulti\b", re.I),
    re.compile(r"\bdual[\s._-]?audio\b", re.I),
    re.compile(r"\bdubbed\b", re.I),
]

LANGUAGE_ALIASES: Dict[str, List[str]] = {
    "English":   ["english", "eng"],
    "Hindi":     ["hindi", "hin"],
    "Tamil":     ["tamil", "tam"],
    "Telugu":    ["telugu", "tel"],
    "Malayalam": ["malayalam", "mal"],
    "Kannada":   ["kannada", "kan"],
    "Bengali":   ["bengali", "bangla"],
    "Marathi":   ["marathi"],
    "Punjabi":   ["punjabi"],
    "Gujarati":  ["gujarati"],
    "Urdu":      ["urdu"],
    "Korean":    ["korean"],
    "Japanese":  ["japanese"],
    "Chinese":   ["chinese", "mandarin"],
    "Thai":      ["thai"],
    "Spanish":   ["spanish"],
    "French":    ["french"],
    "German":    ["german"],
    "Italian":   ["italian"],
    "Portuguese":["portuguese"],
    "Russian":   ["russian"],
    "Turkish":   ["turkish"],
    "Arabic":    ["arabic"],
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


def _smart_title_case(s: str) -> str:
    if not s: return ""
    small = {"of", "the", "and", "or", "a", "an", "in", "on", "at",
             "to", "for", "by", "with", "from"}
    parts = s.split()
    if not parts: return ""
    out = [parts[0].capitalize()]
    for w in parts[1:]:
        out.append(w.lower() if w.lower() in small else w.capitalize())
    return " ".join(out)


def _parse_size_from_name(name: str) -> int:
    m = SIZE_REGEX.search(name)
    if not m: return 0
    try:
        val = float(m.group(1))
        unit = m.group(2).upper()
        if unit in ("GB", "GIB"): return int(val * 1024 * 1024 * 1024)
        if unit in ("MB", "MIB"): return int(val * 1024 * 1024)
    except Exception:
        pass
    return 0


def _detect_from_patterns(name: str, patterns) -> Optional[str]:
    for pat, label in patterns:
        if pat.search(name):
            return label
    return None


def parse_filename(filename: str) -> Dict[str, Any]:
    """Extract structured data from any messy filename."""
    result: Dict[str, Any] = {
        "raw": filename,
        "title": "", "title_slug": "",
        "year": None, "season": None, "episode": None,
        "quality": None, "quality_rank": 0,
        "codec": None, "source": None, "audio_codec": None,
        "is_multi": False,
        "languages": [],
        "size_from_name": 0,
        "is_series": False, "is_season_pack": False,
    }
    if not filename:
        return result

    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts)$",
                  "", name, flags=re.IGNORECASE)
    work = name
    work_lower = work.lower()

    # Season / Episode
    season = episode = None
    for pat in SE_PATTERNS:
        m = pat.search(work)
        if m:
            try:
                season = int(m.group(1))
                episode = int(m.group(2))
                break
            except (TypeError, ValueError, IndexError):
                continue

    if season is None:
        for pat in SEASON_ONLY_PATTERNS:
            m = pat.search(work)
            if m:
                try:
                    season = int(m.group(1))
                    result["is_season_pack"] = True
                    break
                except (TypeError, ValueError, IndexError):
                    continue

    result["season"] = season
    result["episode"] = episode

    # Year
    ym = YEAR_PATTERN.search(work)
    if ym:
        try: result["year"] = int(ym.group(1))
        except (TypeError, ValueError): pass

    # Quality
    for marker, label in QUALITY_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", work_lower):
            result["quality"] = label
            result["quality_rank"] = QUALITY_RANK.get(label, 0)
            break

    # Codec / Source / Audio
    result["codec"] = _detect_from_patterns(work_lower, CODEC_PATTERNS)
    result["source"] = _detect_from_patterns(work_lower, SOURCE_PATTERNS)
    result["audio_codec"] = _detect_from_patterns(work_lower, AUDIO_PATTERNS)

    if result.get("quality") in ("CAM", "HDCAM"):
        result["source"] = result.get("source") or "CAM"
    if result.get("quality") == "TS":
        result["source"] = result.get("source") or "TS"

    # Multi
    result["is_multi"] = any(p.search(work_lower) for p in MULTI_AUDIO_MARKERS)

    # Languages
    langs = []
    for lang_name, aliases in LANGUAGE_ALIASES.items():
        for alias in aliases:
            if re.search(r"\b" + re.escape(alias) + r"\b", work_lower):
                if lang_name not in langs:
                    langs.append(lang_name)
                break
    result["languages"] = langs

    # Size
    result["size_from_name"] = _parse_size_from_name(name)

    # Type
    if season is not None or episode is not None:
        result["is_series"] = True

    # Title cleanup
    title_work = work
    for pat in SE_PATTERNS:
        title_work = pat.sub(" ", title_work)
    for pat in SEASON_ONLY_PATTERNS:
        title_work = pat.sub(" ", title_work)
    if result["year"]:
        title_work = re.sub(r"\b" + str(result["year"]) + r"\b", " ", title_work)
    for marker, _ in QUALITY_MARKERS:
        title_work = re.sub(r"\b" + re.escape(marker) + r"\b", " ",
                            title_work, flags=re.IGNORECASE)
    for lang in langs:
        for alias in LANGUAGE_ALIASES.get(lang, []):
            title_work = re.sub(r"\b" + re.escape(alias) + r"\b", " ",
                                title_work, flags=re.IGNORECASE)
    for noise in NOISE_WORDS:
        title_work = re.sub(r"\b" + re.escape(noise) + r"\b", " ",
                            title_work, flags=re.IGNORECASE)

    # ⭐ STRIP UPLOADER / RELEASE GROUP TAGS
    title_work = re.sub(r"[-_.\s]*@\w+\b", " ", title_work)
    title_work = re.sub(r"[-_.\s]*\[[^\]]{1,40}\]", " ", title_work)
    title_work = re.sub(r"[-_.\s]*\([^\)]{1,20}\)\s*$", " ", title_work)
    title_work = re.sub(
        r"[-_.\s]*(?:rarbg|eztv|yts|yify|galaxyrg|psa|hon3y|bolly4u|"
        r"subsplease|evo|fgt|nf|amzn|thetvshare|tvshare|hdhub4u|"
        r"mkvcage|shaanig|dusicyon|tamilrockers|isaimini)\b",
        " ", title_work, flags=re.IGNORECASE)

    title_work = re.sub(r"[._\-]+", " ", title_work)
    title_work = re.sub(r"\s+", " ", title_work).strip()

    parts = [p for p in title_work.split() if len(p) > 1]
    title_clean = " ".join(parts)

    result["title"] = _smart_title_case(title_clean)
    result["title_slug"] = re.sub(r"[^a-z0-9]+", "_",
                                   result["title"].lower()).strip("_")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# FILE QUALITY SCORING ENGINE
# ═══════════════════════════════════════════════════════════════════════════
RESOLUTION_SCORE = QUALITY_RANK

CODEC_BONUS = {"AV1": 10, "X265": 8, "X264": 4, "MPEG": 0, None: 2}
SOURCE_BONUS = {"REMUX": 15, "BLURAY": 12, "WEBDL": 10, "WEBRIP": 7,
                "HDTV": 4, "DVDRIP": 3, "SCR": 2, "CAM": 0, "TS": 0, None: 2}
AUDIO_BONUS = {"ATMOS": 8, "TRUEHD": 7, "DTS-HD": 6, "DTSX": 6, "DTS": 5,
               "DDP7.1": 5, "DDP5.1": 4, "DDP": 3, "AC3": 2, "AAC": 2,
               "FLAC": 5, "OPUS": 2, "MP3": 1, None: 1}


def _compute_file_score(f: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    resolution = (f.get("quality") or "UNKNOWN").upper()
    codec = (f.get("codec") or "").upper() or None
    source = (f.get("source") or "").upper() or None
    audio = (f.get("audio_codec") or "").upper() or None
    languages = f.get("languages") or []
    size_bytes = f.get("size") or f.get("size_from_name") or 0

    r_score = RESOLUTION_SCORE.get(resolution, 25)
    c_bonus = CODEC_BONUS.get(codec, 2)
    s_bonus = SOURCE_BONUS.get(source, 2)
    a_bonus = AUDIO_BONUS.get(audio, 1)
    l_bonus = len(languages) * 2

    try:
        size_mb = max(0, size_bytes) / (1024 * 1024)
        size_bonus = min(20.0, size_mb / 500.0)
    except Exception:
        size_bonus = 0.0

    total = (r_score + c_bonus + s_bonus + a_bonus + l_bonus + size_bonus)
    return round(total, 1), {
        "resolution": r_score, "codec": c_bonus, "source": s_bonus,
        "audio": a_bonus, "languages": l_bonus,
        "size": round(size_bonus, 1), "total": round(total, 1),
    }


def _pick_best_file(files: List[Dict[str, Any]]) -> Tuple[Optional[Dict], List[Dict]]:
    if not files:
        return None, []
    scored = [( _compute_file_score(f)[0], f) for f in files]
    if all((f.get("quality") or "UNKNOWN").upper() == "UNKNOWN"
           for _, f in scored):
        return None, []
    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]
    best["_score"] = scored[0][0]
    others = []
    for s, f in scored[1:]:
        f["_score"] = s
        others.append(f)
    return best, others


# ═══════════════════════════════════════════════════════════════════════════
# CATALOG
# ═══════════════════════════════════════════════════════════════════════════
class SeriesCatalog:
    def __init__(self):
        self.data: Dict[str, Dict[str, Any]] = {}

    def add(self, parsed: Dict[str, Any], file_record: Dict[str, Any]) -> None:
        if not parsed.get("is_series"): return
        if parsed.get("season") is None: return
        slug = parsed["title_slug"]
        if not slug: return

        if slug not in self.data:
            self.data[slug] = {
                "title": parsed["title"],
                "seasons": defaultdict(lambda: defaultdict(list)),
                "file_count": 0,
            }

        season = parsed["season"]
        episode = parsed.get("episode")

        size_bytes = (file_record.get("file_size")
                       or file_record.get("size")
                       or parsed.get("size_from_name") or 0)

        entry = {
            "file_id": (file_record.get("file_id")
                        or file_record.get("file_unique_id") or ""),
            "file_name": parsed.get("raw", ""),
            "quality": (parsed.get("quality") or "UNKNOWN").upper(),
            "quality_rank": QUALITY_RANK.get(parsed.get("quality") or "", 0),
            "codec": (parsed.get("codec") or "").upper() or None,
            "source": (parsed.get("source") or "").upper() or None,
            "audio_codec": (parsed.get("audio_codec") or "").upper() or None,
            "is_multi": parsed.get("is_multi", False),
            "languages": parsed.get("languages", []),
            "size": size_bytes,
            "size_from_name": parsed.get("size_from_name", 0),
            "chat_id": file_record.get("chat_id"),
            "message_id": file_record.get("message_id") or file_record.get("msg_id"),
            "raw": file_record,
        }

        self.data[slug]["seasons"][season][episode].append(entry)
        self.data[slug]["file_count"] += 1

    def list_series(self) -> List[Dict[str, Any]]:
        out = []
        for slug, info in self.data.items():
            out.append({
                "title_slug": slug,
                "title": info["title"],
                "file_count": info["file_count"],
                "season_count": len(info["seasons"]),
            })
        out.sort(key=lambda x: x["title"].lower())
        return out


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_main(auto_on: bool, completed: int, total: int):
    auto_label = "🟢 AUTO MODE ON" if auto_on else "🔴 AUTO MODE OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(auto_label, callback_data="ai:toggle_auto")],
        [InlineKeyboardButton("🚀 AUTO SCAN", callback_data="ai:auto"),
         InlineKeyboardButton("✍️ MANUAL SCAN", callback_data="ai:manual")],
        [InlineKeyboardButton(f"📚 ALL SERIES ({total})", callback_data="ai:all"),
         InlineKeyboardButton(f"✅ COMPLETED ({completed})", callback_data="ai:completed")],
        [InlineKeyboardButton("🎯 QUALITY PREFS", callback_data="ai:prefs"),
         InlineKeyboardButton("📊 STATUS", callback_data="ai:last_report")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data="ai:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
    ])


def kb_scan_result(title_slug: str, series_index: int, total_series: int):
    rows = [
        [InlineKeyboardButton("👁️ VIEW FILES",
                              callback_data=f"ai:view:{title_slug}")],
        [InlineKeyboardButton("🎯 SET KEEP QUALITIES",
                              callback_data=f"ai:pref:{title_slug}")],
        [InlineKeyboardButton("✅ MARK COMPLETE",
                              callback_data=f"ai:complete:{title_slug}")],
    ]
    if series_index < total_series:
        rows.append([InlineKeyboardButton(
            f"⏭️ NEXT SERIES ({series_index + 1}/{total_series})",
            callback_data=f"ai:next:{title_slug}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_series_list(series_list: List[Dict[str, Any]]):
    rows = []
    for s in series_list[:25]:
        title = (s.get("title") or "?")[:32]
        count = s.get("file_count", 0)
        rows.append([InlineKeyboardButton(
            f"🎬 {title} · {count}",
            callback_data=f"ai:view:{s['title_slug']}"
        )])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_episode_files(title_slug: str, season: int, episode: Optional[int],
                     files: List[Dict[str, Any]]):
    rows = []
    for i, f in enumerate(files[:10]):
        q = f.get("quality", "?")
        langs = "+".join(f.get("languages", [])) or "?"
        rows.append([InlineKeyboardButton(
            f"🗑️ {i+1}. {q} · {langs}",
            callback_data=f"ai:del_pick:{title_slug}:{season}:"
                          f"{episode if episode is not None else 0}:{i}"
        )])
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=f"ai:view:{title_slug}"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_delete(title_slug: str, season: int, episode: Optional[int],
                     file_index: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ YES, DELETE",
                               callback_data=f"ai:del_go:{title_slug}:"
                                             f"{season}:"
                                             f"{episode if episode is not None else 0}:"
                                             f"{file_index}")],
        [InlineKeyboardButton("❌ CANCEL",
                               callback_data=f"ai:view:{title_slug}")],
    ])


def kb_quality_picker(title_slug: str, available: List[str],
                      current: List[str]):
    rows = []
    row = []
    for q in available:
        mark = "✅" if q in current else "⬜"
        row.append(InlineKeyboardButton(
            f"{mark} {q}",
            callback_data=f"ai:pref_tog:{title_slug}:{q}"
        ))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)

    rows.append([InlineKeyboardButton("💾 SAVE",
                                       callback_data=f"ai:pref_save:{title_slug}")])
    rows.append([InlineKeyboardButton("◀️ BACK",
                                       callback_data=f"ai:view:{title_slug}"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_back(target: str = "ai:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close"),
    ]])


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_main() -> Tuple[str, InlineKeyboardMarkup]:
    auto_on = await _get_setting("auto_mode", True)
    completed = await _count_completed()
    total_series = await _get_setting("total_series", 0)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎛️ <b>{fb('AI LIBRARIAN')}</b>",
        DIV, "",
        f"⚙️ {sc('auto mode')} · {'🟢 ᴏɴ' if auto_on else '🔴 ᴏꜰꜰ'}",
        f"✅ {sc('completed series')} · <code>{_fmt_int(completed)}</code>",
        f"📚 {sc('total series')} · <code>{_fmt_int(total_series)}</code>",
        "",
        DIV2, "",
        f"🚀 {sc('auto')} · ᴀɴᴀʟʏᴢᴇ 3 ꜱᴇʀɪᴇꜱ ꜰʀᴏᴍ ᴅʙ",
        f"✍️ {sc('manual')} · ꜱᴇᴀʀᴄʜ ᴏɴᴇ ꜱᴇʀɪᴇꜱ ʙʏ ɴᴀᴍᴇ",
        f"🎯 {sc('quality prefs')} · ᴘɪᴄᴋ ᴡʜɪᴄʜ ǫᴜᴀʟɪᴛɪᴇꜱ ᴛᴏ ᴋᴇᴇᴘ",
        "",
        DIV2,
        f"🕒 {sc('now')} · <code>{_now_ist()}</code>",
    ])
    return text, kb_main(auto_on, completed, total_series)


def _progress_bar(pct: float, width: int = 16) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(width * pct / 100.0)
    empty = width - filled
    if pct >= 75: block = "🟩"
    elif pct >= 50: block = "🟨"
    elif pct >= 25: block = "🟧"
    else: block = "🟥"
    return block * filled + "⬛" * empty + f"  {pct:.0f}%"


def _view_scanning(current: int, total: int) -> str:
    pct = (current / total) * 100 if total else 0
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('SCANNING')}</b>",
        DIV, "",
        f"<code>{_progress_bar(pct)}</code>",
        "",
        f"📁 <code>{_fmt_int(current)}</code> / "
        f"<code>{_fmt_int(total)}</code> ꜰɪʟᴇꜱ",
    ])


def _view_series_result(series: Dict[str, Any], prefs: List[str],
                        index: int, total: int) -> str:
    title = series.get("title") or "?"
    seasons = series.get("seasons") or {}

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>",
        f"📄 {sc('series')} · <code>{index}/{total}</code>",
        DIV, "",
    ]

    total_files = 0
    for snum in sorted(seasons.keys()):
        eps = seasons[snum]
        lines.append(f"📺 <b>{sc('season')} {snum}</b> · "
                     f"<code>{len(eps)} ᴇᴘɪꜱᴏᴅᴇꜱ</code>")

        quality_map: Dict[str, Set[int]] = defaultdict(set)
        for ep, files in eps.items():
            for f in files:
                quality_map[f.get("quality", "?")].add(ep if ep is not None else 0)
                total_files += 1

        for q in sorted(quality_map.keys(),
                        key=lambda x: QUALITY_RANK.get(x, 0),
                        reverse=True):
            eps_present = sorted(quality_map[q])
            present_str = ", ".join(f"E{e:02d}" if e else "?"
                                    for e in eps_present[:15])
            if len(eps_present) > 15:
                present_str += f" +{len(eps_present) - 15}"
            marker = ""
            if prefs and q not in prefs:
                marker = " · 🗑️ ᴛᴏ ᴅᴇʟᴇᴛᴇ"
            elif prefs and q in prefs:
                marker = " · ✅ ᴋᴇᴇᴘ"
            lines.append(f"   🎯 <code>{q}</code> · "
                         f"<code>{present_str}</code>{marker}")
        lines.append("")

    lines.append(DIV2)
    lines.append(f"📁 {sc('total files')} · <code>{_fmt_int(total_files)}</code>")
    if prefs:
        lines.append(f"🎯 {sc('keep qualities')} · "
                     f"<code>{', '.join(prefs)}</code>")
    else:
        lines.append(f"🎯 {sc('keep qualities')} · <i>not set</i>")
    return "\n".join(lines)


def _view_episode_files(title: str, season: int, episode: Optional[int],
                        files: List[Dict[str, Any]],
                        prefs: List[str]) -> str:
    ep_label = f"S{season:02d}" + (f"E{episode:02d}" if episode else "")
    best, _ = _pick_best_file(files)

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b> · <code>{ep_label}</code>",
        DIV, "",
        f"📁 <code>{len(files)}</code> ꜰɪʟᴇꜱ",
        "",
    ]

    for i, f in enumerate(files[:10]):
        q_ = f.get("quality", "?")
        langs = "+".join(f.get("languages", [])) or "?"
        size = _fmt_size(f.get("size", 0) or f.get("size_from_name", 0))
        codec = f.get("codec") or "?"
        source = f.get("source") or "?"
        score = f.get("_score", 0)

        tag = ""
        if f is best:
            tag = " · ⭐ ʙᴇꜱᴛ"
        elif prefs and q_ not in prefs:
            tag = " · 🗑️ ʀᴇᴍᴏᴠᴇ"
        elif q_ == "UNKNOWN":
            tag = " · ⚠️ ᴜɴᴋɴᴏᴡɴ"

        lines.append(f"<b>{i+1}.</b> <code>{q_}</code> · "
                     f"<code>{codec}</code> · <code>{source}</code>{tag}")
        lines.append(f"   🌍 <code>{langs}</code> · 📦 {size}")

    lines.append("")
    lines.append(DIV2)
    lines.append(f"📌 {sc('tap a file to delete it')}")
    return "\n".join(lines)


def _view_confirm_delete(title: str, season: int, episode: Optional[int],
                        f: Dict[str, Any]) -> str:
    ep_label = f"S{season:02d}" + (f"E{episode:02d}" if episode else "")
    q = f.get("quality", "?")
    langs = "+".join(f.get("languages", [])) or "?"
    size = _fmt_size(f.get("size", 0) or f.get("size_from_name", 0))
    return "\n".join([
        f"⚠️ <b>{fb('CONFIRM DELETE')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b> · <code>{ep_label}</code>",
        f"🎯 {sc('quality')} · <code>{q}</code>",
        f"🌍 {sc('languages')} · <code>{langs}</code>",
        f"📦 {sc('size')} · <code>{size}</code>",
        "",
        DIV2, "",
        f"❗ <b>{sc('this cannot be undone')}</b>",
    ])


def _view_quality_picker(title: str, available: List[str],
                        current: List[str]) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('QUALITY PREFERENCES')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        "",
        f"📌 {sc('pick which qualities to keep')}",
        f"📌 {sc('others will be marked as deletable')}",
        "",
        DIV2, "",
        f"📊 {sc('qualities found')} · <code>{', '.join(available) or 'none'}</code>",
        f"✅ {sc('currently keeping')} · <code>{', '.join(current) or 'none'}</code>",
    ])


# ═══════════════════════════════════════════════════════════════════════════
# SAFE EDIT
# ═══════════════════════════════════════════════════════════════════════════
async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.exception(f"[AI] edit: {type(e).__name__}: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SCAN LIBRARY (reads MANY DB field names)
# ═══════════════════════════════════════════════════════════════════════════
async def _scan_library(client: Client, chat_id: int, status_msg_id: int,
                       filter_slug: Optional[str] = None) -> Optional[SeriesCatalog]:
    coll = _files_coll()
    if coll is None:
        return None

    try:
        total = await coll.estimated_document_count()
    except Exception:
        total = 0
    if total == 0:
        return SeriesCatalog()

    catalog = SeriesCatalog()
    processed = 0
    last_edit = 0.0

    try:
        cursor = coll.find({})
        async for doc in cursor:
            processed += 1

            # ⭐ Try EVERY possible DB field name for the filename
            fname = (
                doc.get("file_name")
                or doc.get("filename")
                or doc.get("title")
                or doc.get("name")
                or doc.get("file_title")
                or doc.get("caption")
                or doc.get("file_caption")
                or doc.get("media_title")
                or ""
            )

            # Fallback: if no field matched, search any string field
            if not fname:
                for k, v in doc.items():
                    if k in ("_id", "chat_id", "message_id", "msg_id",
                             "file_id", "file_unique_id", "file_size", "size"):
                        continue
                    if isinstance(v, str) and len(v) > 5:
                        if any(ext in v.lower() for ext in
                               (".mkv", ".mp4", ".avi", ".mov", ".webm", ".ts")):
                            fname = v
                            break

            if not fname:
                continue

            parsed = parse_filename(str(fname))

            if filter_slug is not None:
                slug_match = parsed.get("title_slug", "")
                if (filter_slug not in slug_match
                        and slug_match not in filter_slug):
                    continue

            catalog.add(parsed, doc)

            now = time.time()
            if now - last_edit >= PROGRESS_UPDATE_INTERVAL:
                last_edit = now
                try:
                    await client.edit_message_text(
                        chat_id=chat_id, message_id=status_msg_id,
                        text=_view_scanning(processed, total),
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass

        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=status_msg_id,
                text=_view_scanning(processed, total),
                parse_mode=ParseMode.HTML)
        except Exception:
            pass

        return catalog
    except Exception as e:
        logger.exception(f"[AI] scan failed: {e}")
        return catalog


# ═══════════════════════════════════════════════════════════════════════════
# /ai COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["ai", "librarian", "ailib"]) & filters.private,
    group=-430,
)
async def cmd_ai(client: Client, message: Message):
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        _clear_session(message.from_user.id)
        text, kb = await _view_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[AI] /ai crashed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DIAGNOSTIC /aidb COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["aidb", "ai_dbcheck", "aidbcheck"]) & filters.private,
    group=-430,
)
async def cmd_aidb(client: Client, message: Message):
    """Show what fields exist in media_files collection."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    coll = _files_coll()
    if coll is None:
        return await message.reply_text("❌ ᴅʙ ɴᴏᴛ ᴀᴄᴄᴇꜱꜱɪʙʟᴇ.")

    try:
        total = await coll.estimated_document_count()
        sample = await coll.find_one({})
        if not sample:
            return await message.reply_text("⚪ ᴅʙ ɪꜱ ᴇᴍᴘᴛʏ.")

        sample.pop("_id", None)
        fields = sorted(sample.keys())

        # Try to find a Game of Thrones-like file
        gof = None
        for field in ("file_name", "filename", "title", "name",
                      "caption", "file_caption", "media_title"):
            try:
                gof = await coll.find_one(
                    {field: {"$regex": "Thrones", "$options": "i"}})
                if gof: break
            except Exception:
                continue

        lines = [
            "🔍 <b>ᴅʙ ᴅɪᴀɢɴᴏꜱᴛɪᴄꜱ</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"📁 ᴛᴏᴛᴀʟ ꜰɪʟᴇꜱ · <code>{_fmt_int(total)}</code>",
            "",
            "🔑 <b>ꜰɪᴇʟᴅꜱ ɪɴ ᴅʙ</b>",
        ]
        for f in fields[:40]:
            lines.append(f"  • <code>{f}</code>")

        if gof:
            gof.pop("_id", None)
            lines.append("")
            lines.append("🎬 <b>ꜱᴀᴍᴘʟᴇ 'ᴛʜʀᴏɴᴇꜱ' ꜰɪʟᴇ</b>")
            for k, v in list(gof.items())[:20]:
                v_str = str(v)[:90]
                lines.append(f"  <code>{k}</code> = {_esc(v_str)}")
        else:
            lines.append("")
            lines.append("⚠️ ɴᴏ 'ᴛʜʀᴏɴᴇꜱ' ꜰɪʟᴇ ꜰᴏᴜɴᴅ ɪɴ ʀᴇɢᴜʟᴀʀ ꜰɪᴇʟᴅꜱ")

        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        await message.reply_text(f"❌ {_esc(e)}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN PANEL CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:main$"), group=-430)
async def cb_main(client: Client, q: CallbackQuery):
    try:
        text, kb = await _view_main()
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] cb_main: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:close$"), group=-430)
async def cb_close(client: Client, q: CallbackQuery):
    try:
        _clear_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        try: await q.answer("ᴄʟᴏꜱᴇᴅ")
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:toggle_auto$"), group=-430)
async def cb_toggle_auto(client: Client, q: CallbackQuery):
    try:
        current = await _get_setting("auto_mode", True)
        new_val = not current
        await _set_setting("auto_mode", new_val)
        await q.answer("🟢 ᴀᴜᴛᴏ ᴏɴ" if new_val else "🔴 ᴀᴜᴛᴏ ᴏꜰꜰ")
        text, kb = await _view_main()
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[AI] toggle: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# AUTO SCAN
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:auto$"), group=-430)
async def cb_auto(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        await q.answer("🚀 ꜱᴄᴀɴɴɪɴɢ...")

        try:
            status = await q.message.edit_text(
                _view_scanning(0, 0), parse_mode=ParseMode.HTML)
        except Exception:
            status = q.message

        catalog = await _scan_library(client, q.message.chat.id, status.id)
        if catalog is None:
            return await client.edit_message_text(
                chat_id=q.message.chat.id, message_id=status.id,
                text="⚠️ ᴅᴀᴛᴀʙᴀꜱᴇ ᴜɴᴀᴠᴀɪʟᴀʙʟᴇ.",
                parse_mode=ParseMode.HTML)

        all_series = catalog.list_series()
        await _set_setting("total_series", len(all_series))

        pending: List[Dict[str, Any]] = []
        for s in all_series:
            if await _is_completed(s["title_slug"]):
                continue
            pending.append(s)

        if not pending:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=status.id,
                    text="\n".join([
                        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                        f"✅ <b>{fb('ALL SERIES REVIEWED')}</b>",
                        DIV, "",
                        f"🎉 {sc('every series is marked complete')}",
                    ]),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close"),
                    ]]),
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return

        random.shuffle(pending)
        picked = pending[:SERIES_PER_AUTO]

        _new_session(q.from_user.id, "auto_scan",
                     picked=[s["title_slug"] for s in picked],
                     index=0)
        sess = _SESSIONS[q.from_user.id]
        sess["catalog_data"] = catalog.data
        sess["current_total"] = len(picked)

        await _show_series_by_slug(
            client, q.message.chat.id, status.id,
            picked[0]["title_slug"], 1, len(picked))
    except Exception as e:
        logger.exception(f"[AI] cb_auto: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# MANUAL SCAN
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:manual$"), group=-430)
async def cb_manual(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        _new_session(q.from_user.id, "manual_name")
        await _safe_edit(q,
            "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"✍️ <b>{fb('MANUAL SCAN')}</b>",
                DIV, "",
                f"📝 {sc('send the series name as next message')}",
                "",
                f"📌 {sc('example')} · <code>Game of Thrones</code>",
            ]),
            InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")]]))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] cb_manual: {e}")


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-429,
)
async def ai_manual_input(client: Client, message: Message):
    if not message.from_user: return
    session = _get_session(message.from_user.id)
    if not session or session["action"] != "manual_name":
        return

    try: message.stop_propagation()
    except Exception: pass

    text = (message.text or "").strip()
    if len(text) < 2:
        return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")

    _clear_session(message.from_user.id)
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

    try:
        status = await message.reply_text(
            _view_scanning(0, 0), parse_mode=ParseMode.HTML)
    except Exception:
        return

    catalog = await _scan_library(client, message.chat.id, status.id,
                                   filter_slug=slug)

    if catalog is None or not catalog.data:
        try:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=status.id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('NOT FOUND')}</b>",
                    DIV, "",
                    f"🔍 {sc('searched')} · <code>{_esc(text)}</code>",
                    "",
                    f"📌 {sc('no matching series in your db')}",
                    f"📌 {sc('try a different name')}",
                ]),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✍️ TRY AGAIN",
                                           callback_data="ai:manual")],
                    [InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                     InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
                ]),
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    slugs = list(catalog.data.keys())
    first_slug = slugs[0]

    _new_session(message.from_user.id, "manual_result",
                 slug=first_slug, all_slugs=slugs)
    sess = _SESSIONS[message.from_user.id]
    sess["catalog_data"] = catalog.data

    await _show_series_by_slug(
        client, message.chat.id, status.id,
        first_slug, 1, 1)


# ═══════════════════════════════════════════════════════════════════════════
# SHOW SERIES
# ═══════════════════════════════════════════════════════════════════════════
async def _show_series_by_slug(client: Client, chat_id: int,
                                msg_id: int, title_slug: str,
                                index: int, total: int):
    sess = None
    for uid, s in _SESSIONS.items():
        if "catalog_data" in s:
            sess = s
            break

    if not sess or not sess.get("catalog_data"):
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="⚠️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ. ᴛʀʏ ᴀɢᴀɪɴ.",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    data = sess["catalog_data"]
    series = data.get(title_slug)
    if not series:
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="⚠️ ꜱᴇʀɪᴇꜱ ɴᴏᴛ ꜰᴏᴜɴᴅ.",
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    prefs = await _get_prefs(title_slug)
    text = _view_series_result(
        {"title": series.get("title"), "seasons": series.get("seasons")},
        prefs, index, total)
    kb = kb_scan_result(title_slug, index, total)

    sess["current_slug"] = title_slug
    sess["current_index"] = index
    sess["current_total"] = total

    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except MessageNotModified:
        pass
    except Exception as e:
        logger.debug(f"[AI] show series: {e}")


@Client.on_callback_query(filters.regex(r"^ai:next:([a-z0-9_]+)$"), group=-430)
async def cb_next(client: Client, q: CallbackQuery):
    try:
        sess = _get_session(q.from_user.id)
        if not sess:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        data = sess.get("data") or {}
        picked = data.get("picked") or []
        idx = data.get("index", 0) + 1
        if idx >= len(picked):
            return await q.answer("✅ ᴀʟʟ ᴅᴏɴᴇ", show_alert=True)
        sess["data"]["index"] = idx
        next_slug = picked[idx]
        await q.answer()
        await _show_series_by_slug(
            client, q.message.chat.id, q.message.id,
            next_slug, idx + 1, len(picked))
    except Exception as e:
        logger.exception(f"[AI] next: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# VIEW FILES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:view:([a-z0-9_]+)$"), group=-430)
async def cb_view_series(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        sess = _get_session(q.from_user.id)
        if not sess or not sess.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        data = sess["catalog_data"]
        series = data.get(slug)
        if not series:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        seasons = series.get("seasons") or {}
        if not seasons:
            return await q.answer("⚠️ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)
        first_season = sorted(seasons.keys())[0]
        eps = seasons[first_season]
        first_ep = sorted([e for e in eps.keys() if e is not None])[0] \
            if any(e is not None for e in eps.keys()) else None
        if first_ep is None:
            return await q.answer("⚠️ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ", show_alert=True)
        files = eps[first_ep]
        # Score all files
        for f in files:
            f["_score"] = _compute_file_score(f)[0]
        prefs = await _get_prefs(slug)
        text = _view_episode_files(series.get("title"), first_season,
                                    first_ep, files, prefs)
        kb = kb_episode_files(slug, first_season, first_ep, files)
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] view series: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# QUALITY PREFS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:pref:([a-z0-9_]+)$"), group=-430)
async def cb_pref(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        sess = _get_session(q.from_user.id)
        if not sess or not sess.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        data = sess["catalog_data"]
        series = data.get(slug)
        if not series:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        available: Set[str] = set()
        for snum, eps in (series.get("seasons") or {}).items():
            for ep, files in eps.items():
                for f in files:
                    q_ = f.get("quality")
                    if q_: available.add(q_)
        avail_list = sorted(available,
                            key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True)
        if not avail_list:
            return await q.answer("⚠️ ɴᴏ ǫᴜᴀʟɪᴛɪᴇꜱ", show_alert=True)
        current = await _get_prefs(slug)
        sess["pref_working"] = list(current)
        text = _view_quality_picker(series.get("title"), avail_list, current)
        kb = kb_quality_picker(slug, avail_list, current)
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] pref: {e}")


@Client.on_callback_query(
    filters.regex(r"^ai:pref_tog:([a-z0-9_]+):(\w+)$"), group=-430)
async def cb_pref_toggle(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        quality = q.matches[0].group(2)
        sess = _get_session(q.from_user.id)
        if not sess:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        working = sess.get("pref_working") or []
        if quality in working:
            working.remove(quality)
        else:
            working.append(quality)
        sess["pref_working"] = working
        data = sess.get("catalog_data") or {}
        series = data.get(slug) or {}
        available: Set[str] = set()
        for snum, eps in (series.get("seasons") or {}).items():
            for ep, files in eps.items():
                for f in files:
                    q_ = f.get("quality")
                    if q_: available.add(q_)
        avail_list = sorted(available,
                            key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True)
        text = _view_quality_picker(series.get("title"), avail_list, working)
        kb = kb_quality_picker(slug, avail_list, working)
        await _safe_edit(q, text, kb)
        await q.answer("✅" if quality in working else "⬜")
    except Exception as e:
        logger.exception(f"[AI] pref_tog: {e}")


@Client.on_callback_query(
    filters.regex(r"^ai:pref_save:([a-z0-9_]+)$"), group=-430)
async def cb_pref_save(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        sess = _get_session(q.from_user.id)
        if not sess:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        working = sess.get("pref_working") or []
        data = sess.get("catalog_data") or {}
        series = data.get(slug) or {}
        title = series.get("title") or slug
        ok = await _set_prefs(slug, title, working)
        await q.answer("✅ ꜱᴀᴠᴇᴅ" if ok else "❌ ꜰᴀɪʟᴇᴅ")
        if not ok: return
        text = _view_series_result(
            {"title": title, "seasons": series.get("seasons")},
            working,
            sess.get("current_index", 1),
            sess.get("current_total", 1))
        kb = kb_scan_result(slug,
                            sess.get("current_index", 1),
                            sess.get("current_total", 1))
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[AI] pref_save: {e}")


@Client.on_callback_query(filters.regex(r"^ai:prefs$"), group=-430)
async def cb_prefs_list(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        items = await _list_prefs()
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🎯 <b>{fb('QUALITY PREFERENCES')}</b>",
            DIV, "",
        ]
        if not items:
            lines.append("⚪ ɴᴏ ᴘʀᴇꜰᴇʀᴇɴᴄᴇꜱ ꜱᴇᴛ ʏᴇᴛ.")
        else:
            for it in items[:30]:
                title = it.get("title") or "?"
                qs = it.get("keep_qualities") or []
                lines.append(f"🎬 <b>{_esc(title)}</b>")
                lines.append(f"   ✅ <code>{', '.join(qs)}</code>")
                lines.append("")
        await _safe_edit(q, "\n".join(lines), kb_back("ai:main"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] prefs_list: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MARK COMPLETE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^ai:complete:([a-z0-9_]+)$"), group=-430)
async def cb_complete(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        sess = _get_session(q.from_user.id)
        if not sess:
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        data = sess.get("catalog_data") or {}
        series = data.get(slug)
        if not series:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        total_files = series.get("file_count", 0)
        title = series.get("title") or slug
        ok = await _mark_completed(title, slug, total_files)
        if not ok:
            return await q.answer("❌ ꜰᴀɪʟᴇᴅ", show_alert=True)
        await q.answer("✅ ᴍᴀʀᴋᴇᴅ ᴄᴏᴍᴘʟᴇᴛᴇ")
        await _safe_edit(q,
            "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"✅ <b>{fb('MARKED COMPLETE')}</b>",
                DIV, "",
                f"🎬 <b>{_esc(title)}</b>",
                f"📁 {sc('total files')} · <code>{_fmt_int(total_files)}</code>",
                f"📅 {sc('marked')} · <code>{_now_ist()}</code>",
            ]),
            InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭️ NEXT SERIES",
                                       callback_data=f"ai:next:{slug}")],
                [InlineKeyboardButton("◀️ MAIN", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
            ]))
    except Exception as e:
        logger.exception(f"[AI] complete: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ALL SERIES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:all$"), group=-430)
async def cb_all(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")
        try:
            status = await q.message.edit_text(
                _view_scanning(0, 0), parse_mode=ParseMode.HTML)
        except Exception:
            status = q.message
        catalog = await _scan_library(client, q.message.chat.id, status.id)
        if catalog is None:
            return
        all_series = catalog.list_series()
        await _set_setting("total_series", len(all_series))
        if not all_series:
            try:
                await client.edit_message_text(
                    chat_id=q.message.chat.id, message_id=status.id,
                    text="⚪ ɴᴏ ꜱᴇʀɪᴇꜱ ꜰᴏᴜɴᴅ ɪɴ ᴅʙ.",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return
        sess = _SESSIONS.setdefault(q.from_user.id, {})
        sess["catalog_data"] = catalog.data
        completed_slugs = {s.get("title_slug") for s in await _list_completed()}
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📚 <b>{fb('ALL SERIES')}</b>",
            DIV, "",
            f"📊 {sc('total')} · <code>{_fmt_int(len(all_series))}</code>",
            f"✅ {sc('completed')} · <code>{_fmt_int(len(completed_slugs))}</code>",
            "",
            DIV2, "",
        ]
        for s in all_series[:25]:
            mark = "✅" if s["title_slug"] in completed_slugs else "🎬"
            lines.append(f"{mark} <b>{_esc(s['title'])}</b> · "
                         f"<code>{s['file_count']}</code> ꜰɪʟᴇꜱ")
        try:
            await client.edit_message_text(
                chat_id=q.message.chat.id, message_id=status.id,
                text="\n".join(lines),
                reply_markup=kb_series_list(all_series),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"[AI] all list: {e}")
    except Exception as e:
        logger.exception(f"[AI] all: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# COMPLETED LIST
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:completed$"), group=-430)
async def cb_completed(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        items = await _list_completed(limit=50)
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{fb('COMPLETED SERIES')}</b>",
            DIV, "",
        ]
        if not items:
            lines.append("⚪ ɴᴏ ꜱᴇʀɪᴇꜱ ᴍᴀʀᴋᴇᴅ ᴄᴏᴍᴘʟᴇᴛᴇ ʏᴇᴛ.")
        else:
            for it in items[:30]:
                title = it.get("title") or "?"
                ts = it.get("completed_at", 0)
                try:
                    d = datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
                except Exception:
                    d = "?"
                lines.append(f"✅ <b>{_esc(title)}</b>")
                lines.append(f"   📅 <code>{d}</code>")
                lines.append("")
        rows = []
        for it in items[:10]:
            rows.append([InlineKeyboardButton(
                f"🔄 UNMARK · {it.get('title', '?')[:25]}",
                callback_data=f"ai:unmark:{it.get('title_slug')}"
            )])
        rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                     InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
        await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] completed: {e}")


@Client.on_callback_query(
    filters.regex(r"^ai:unmark:([a-z0-9_]+)$"), group=-430)
async def cb_unmark(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        ok = await _unmark_completed(slug)
        await q.answer("✅ ᴜɴᴍᴀʀᴋᴇᴅ" if ok else "❌ ɴᴏᴛ ꜰᴏᴜɴᴅ")
        await cb_completed(client, q)
    except Exception as e:
        logger.exception(f"[AI] unmark: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SMART DELETE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^ai:del_pick:([a-z0-9_]+):(\d+):(\d+):(\d+)$"),
    group=-430)
async def cb_del_pick(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode_raw = int(q.matches[0].group(3))
        idx = int(q.matches[0].group(4))
        episode = episode_raw if episode_raw > 0 else None
        sess = _get_session(q.from_user.id)
        if not sess or not sess.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        data = sess["catalog_data"]
        series = data.get(slug)
        if not series:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        eps = (series.get("seasons") or {}).get(season, {})
        files = eps.get(episode, [])
        if idx < 0 or idx >= len(files):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ", show_alert=True)
        f = files[idx]
        text = _view_confirm_delete(series.get("title"), season, episode, f)
        kb = kb_confirm_delete(slug, season, episode, idx)
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] del_pick: {e}")


@Client.on_callback_query(
    filters.regex(r"^ai:del_go:([a-z0-9_]+):(\d+):(\d+):(\d+)$"),
    group=-430)
async def cb_del_go(client: Client, q: CallbackQuery):
    try:
        slug = q.matches[0].group(1)
        season = int(q.matches[0].group(2))
        episode_raw = int(q.matches[0].group(3))
        idx = int(q.matches[0].group(4))
        episode = episode_raw if episode_raw > 0 else None
        sess = _get_session(q.from_user.id)
        if not sess or not sess.get("catalog_data"):
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        data = sess["catalog_data"]
        series = data.get(slug)
        if not series:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
        eps = (series.get("seasons") or {}).get(season, {})
        files = eps.get(episode, [])
        if idx < 0 or idx >= len(files):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ꜰɪʟᴇ", show_alert=True)
        f = files[idx]
        file_id = f.get("file_id") or ""
        if not file_id:
            return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇ ɪᴅ", show_alert=True)
        ok = await _delete_file_record(file_id)
        if not ok:
            return await q.answer("❌ ᴅᴇʟᴇᴛᴇ ꜰᴀɪʟᴇᴅ", show_alert=True)
        files.pop(idx)
        sess["catalog_data"][slug]["seasons"][season][episode] = files
        await q.answer("🗑️ ᴅᴇʟᴇᴛᴇᴅ")
        for f2 in files:
            f2["_score"] = _compute_file_score(f2)[0]
        prefs = await _get_prefs(slug)
        text = _view_episode_files(series.get("title"), season,
                                    episode, files, prefs)
        kb = kb_episode_files(slug, season, episode, files)
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[AI] del_go: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# DAILY REPORT
# ═══════════════════════════════════════════════════════════════════════════
_LAST_REPORT_DATE: Optional[str] = None


async def _daily_report_loop(client: Client):
    global _LAST_REPORT_DATE
    await asyncio.sleep(120)
    while True:
        try:
            now = datetime.now(IST)
            today_key = now.strftime("%Y-%m-%d")
            auto_on = await _get_setting("auto_mode", True)
            if (auto_on
                    and now.hour == DAILY_REPORT_HOUR
                    and now.minute < 5
                    and _LAST_REPORT_DATE != today_key):
                _LAST_REPORT_DATE = today_key
                await _send_daily_report(client)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[AI] daily loop: {e}")
        await asyncio.sleep(60)


async def _send_daily_report(client: Client):
    try:
        completed_count = await _count_completed()
        total_series = await _get_setting("total_series", 0)
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🎛️ <b>{fb('DAILY AI REPORT')}</b>",
            DIV, "",
            f"📅 <code>{_now_ist()}</code>",
            "",
            f"📚 {sc('total series')} · <code>{_fmt_int(total_series)}</code>",
            f"✅ {sc('completed')} · <code>{_fmt_int(completed_count)}</code>",
            f"⏳ {sc('pending')} · "
            f"<code>{_fmt_int(max(0, total_series - completed_count))}</code>",
            "",
            DIV2, "",
            f"📌 {sc('tap auto to review 3 series today')}",
        ])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 AUTO SCAN", callback_data="ai:auto"),
             InlineKeyboardButton("✍️ MANUAL", callback_data="ai:manual")],
            [InlineKeyboardButton("🎛️ OPEN PANEL", callback_data="ai:main"),
             InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
        ])
        for admin_id in ADMINS:
            try:
                aid = int(admin_id) if str(admin_id).lstrip("-").isdigit() else None
                if not aid: continue
                await client.send_message(
                    chat_id=aid, text=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception as e:
                logger.debug(f"[AI] report to {admin_id}: {e}")
    except Exception as e:
        logger.warning(f"[AI] daily report: {e}")


@Client.on_callback_query(filters.regex(r"^ai:last_report$"), group=-430)
async def cb_last_report(client: Client, q: CallbackQuery):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        completed_count = await _count_completed()
        total_series = await _get_setting("total_series", 0)
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{fb('CURRENT STATUS')}</b>",
            DIV, "",
            f"📚 {sc('total series')} · <code>{_fmt_int(total_series)}</code>",
            f"✅ {sc('completed')} · <code>{_fmt_int(completed_count)}</code>",
            f"⏳ {sc('pending')} · "
            f"<code>{_fmt_int(max(0, total_series - completed_count))}</code>",
            "",
            f"🕒 <code>{_now_ist()}</code>",
        ])
        await _safe_edit(q, text, kb_back("ai:main"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] last_report: {e}")


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


_BOOTED = False


@Client.on_message(filters.private, group=-428)
async def _boot_capture(client: Client, message: Message):
    global _BOOTED
    if _BOOTED: return
    _BOOTED = True
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_daily_report_loop(client))
        loop.create_task(_cleanup_loop())
        logger.info("[AI] background loops started")
    except Exception as e:
        logger.warning(f"[AI] boot: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# FINAL LOG
# ═══════════════════════════════════════════════════════════════════════════
logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  🎛️ AI LIBRARIAN LOADED ✅                                     ║")
logger.info("║                                                                ║")
logger.info("║  Commands:                                                     ║")
logger.info("║    /ai          — open AI panel                                ║")
logger.info("║    /librarian   — alias                                        ║")
logger.info("║    /aidb        — DB diagnostic (shows fields)                 ║")
logger.info("║                                                                ║")
logger.info("║  Fixes:                                                        ║")
logger.info("║    · Strips @TheTvShare, [YTS.MX], -RARBG, etc.                ║")
logger.info("║    · Reads 8+ DB field names for filenames                     ║")
logger.info("║    · Fallback: scans any string field with video ext           ║")
logger.info("║    · Smart file scoring (resolution+codec+source+audio)        ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
