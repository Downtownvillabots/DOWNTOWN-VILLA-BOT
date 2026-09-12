# core/config.py
"""
DOWNTOWN VILLA — central configuration.
Reads from environment variables. All search/indexing/admin features pull from here.
"""
import os
import re
from os import environ, getenv


# ═══════════════════════ UTILITIES ═══════════════════════
def is_enabled(value, default=False) -> bool:
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in ("true", "yes", "1", "enable", "on", "y"):
        return True
    if v in ("false", "no", "0", "disable", "off", "n"):
        return False
    return default


id_pattern = re.compile(r"^.\d+$")


# ═══════════════════════ BOT CONNECTION ═══════════════════════
API_ID = int(environ.get("API_ID", "0"))
API_HASH = environ.get("API_HASH", "")
BOT_TOKEN = environ.get("BOT_TOKEN", "")
SESSION = environ.get("SESSION", "downtown_villa")


# ═══════════════════════ ADMINS ═══════════════════════
ADMINS = [
    int(a) if id_pattern.match(a) else a
    for a in environ.get("ADMINS", "").split()
    if a
]


# ═══════════════════════ LOG CHANNEL ═══════════════════════
LOG_CHANNEL = int(environ.get("LOG_CHANNEL", "0") or 0)


# ═══════════════════════ SERVER / WEB ═══════════════════════
PORT = int(environ.get("PORT", "8080"))


# ═══════════════════════ SUBSCRIPTION / CHANNELS ═══════════════════════
# Force-subscription channels (list of channel IDs)
_auth_channels_raw = environ.get("AUTH_CHANNELS", "")
AUTH_CHANNELS = [
    int(ch) if id_pattern.match(ch) else ch
    for ch in _auth_channels_raw.split()
    if ch and (str(ch).lstrip("-").isdigit())
]

# Additional auth channel ids if you separate them
_auth_req_raw = environ.get("AUTH_REQ_CHANNELS", "")
AUTH_REQ_CHANNELS = [
    int(ch) if id_pattern.match(ch) else ch
    for ch in _auth_req_raw.split()
    if ch and (str(ch).lstrip("-").isdigit())
]

SUPPORT_CHAT = environ.get("SUPPORT_CHAT", "https://t.me/")
_support_chat_id = environ.get("SUPPORT_CHAT_ID", "")
try:
    SUPPORT_CHAT_ID = int(_support_chat_id) if _support_chat_id else None
except (TypeError, ValueError):
    SUPPORT_CHAT_ID = None

GRP_LNK = environ.get("GRP_LNK", "https://t.me/")
UPDATE_CHNL_LNK = environ.get("UPDATE_CHNL_LNK", "https://t.me/")
OWNER_LNK = environ.get("OWNER_LNK", "https://t.me/")


# ═══════════════════════ MOVIE UPDATE ═══════════════════════
_muc = environ.get("MOVIE_UPDATE_CHANNEL", "")
try:
    MOVIE_UPDATE_CHANNEL = int(_muc) if _muc else None
except (TypeError, ValueError):
    MOVIE_UPDATE_CHANNEL = None

MOVIE_UPDATE_NOTIFICATION = is_enabled(
    environ.get("MOVIE_UPDATE_NOTIFICATION", "False"), False
)


# ═══════════════════════ METADATA PROVIDER ═══════════════════════
TMDB_API_KEY = environ.get("TMDB_API_KEY", "")
TMDB_POSTER = is_enabled(environ.get("TMDB_POSTER", "True"), True)
IMDB = is_enabled(environ.get("IMDB", "True"), True)


# ═══════════════════════ CAPTIONS ═══════════════════════
CUSTOM_FILE_CAPTION = environ.get("CUSTOM_FILE_CAPTION", "")
BATCH_FILE_CAPTION = environ.get("BATCH_FILE_CAPTION", CUSTOM_FILE_CAPTION)


# ═══════════════════════ LANGUAGES / QUALITIES / SEASONS ═══════════════════════
LANGUAGES = {
    "ᴍᴀʟᴀʏᴀʟᴀᴍ": "mal",
    "ᴛᴀᴍɪʟ": "tam",
    "ᴇɴɢʟɪꜱʜ": "eng",
    "ʜɪɴᴅɪ": "hin",
    "ᴛᴇʟᴜɢᴜ": "tel",
    "ᴋᴀɴɴᴀᴅᴀ": "kan",
    "ɢᴜᴊᴀʀᴀᴛɪ": "guj",
    "ᴍᴀʀᴀᴛʜɪ": "mar",
    "ᴘᴜɴᴊᴀʙɪ": "pun",
}

QUALITIES = ["360P", "480P", "720P", "1080P", "1440P", "2160P", "4K"]

SEASON_COUNT = 12
SEASONS = [f"S{str(i).zfill(2)}" for i in range(1, SEASON_COUNT + 1)]


# ═══════════════════════ SEARCH / AUTO-FILTER ═══════════════════════
SEARCH_PAGE_SIZE = int(environ.get("SEARCH_PAGE_SIZE", "10"))
MAX_SEARCH_RESULTS = int(environ.get("MAX_SEARCH_RESULTS", "200"))
SEARCH_CACHE_TTL = int(environ.get("SEARCH_CACHE_TTL", "300"))
SEARCH_SESSION_TTL = int(environ.get("SEARCH_SESSION_TTL", "1800"))
SEARCH_SHARD_TIMEOUT = int(environ.get("SEARCH_SHARD_TIMEOUT", "6"))

PREFERRED_QUALITY = environ.get("PREFERRED_QUALITY", "1080P")
PREFERRED_CODEC = environ.get("PREFERRED_CODEC", "HEVC")
PREFERRED_AUDIO = environ.get("PREFERRED_AUDIO", "ENGLISH")
PREFERRED_SUBTITLE = environ.get("PREFERRED_SUBTITLE", "ENGLISH")

METADATA_PROVIDER = environ.get("METADATA_PROVIDER", "tmdb")
METADATA_API_KEY = environ.get("METADATA_API_KEY", TMDB_API_KEY or "")
METADATA_TIMEOUT = int(environ.get("METADATA_TIMEOUT", "3"))
METADATA_CACHE_TTL = int(environ.get("METADATA_CACHE_TTL", "3600"))
METADATA_ENABLED = is_enabled(
    environ.get("METADATA_ENABLED", "True" if METADATA_API_KEY else "False"),
    bool(METADATA_API_KEY),
)

FORCE_SUB_ENABLED = is_enabled(
    environ.get("FORCE_SUB_ENABLED", "True" if AUTH_CHANNELS else "False"),
    bool(AUTH_CHANNELS),
)


# ═══════════════════════ INDEXING ═══════════════════════
DATABASE_CHANNEL_ID_RAW = environ.get("DATABASE_CHANNEL_ID", "")
try:
    DATABASE_CHANNEL_ID = int(DATABASE_CHANNEL_ID_RAW) if DATABASE_CHANNEL_ID_RAW else None
except (TypeError, ValueError):
    DATABASE_CHANNEL_ID = None

AUTO_INDEXING_ENABLED = is_enabled(
    environ.get("AUTO_INDEXING_ENABLED", "True"), True
)
INDEXING_THRESHOLD_MB = int(environ.get("INDEXING_THRESHOLD_MB", "400"))


# ═══════════════════════ AUTO-DELETE ═══════════════════════
AUTO_DELETE_ENABLED = is_enabled(
    environ.get("AUTO_DELETE_ENABLED", "True"), True
)
AUTO_DELETE_MINUTES = int(environ.get("AUTO_DELETE_MINUTES", "10"))
AUTO_DELETE_WARNING = environ.get(
    "AUTO_DELETE_WARNING",
    "⚠️ ᴛʜɪꜱ ꜰɪʟᴇ ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ <b>{minutes} ᴍɪɴᴜᴛᴇꜱ</b>.\n"
    "ᴘʟᴇᴀꜱᴇ ꜱᴀᴠᴇ ᴏʀ ꜱʜᴀʀᴇ ɪᴛ ɴᴏᴡ."
)
