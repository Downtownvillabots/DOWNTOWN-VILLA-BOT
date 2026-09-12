"""
Media Search — central configuration.
Reads from environment, falls back to core.config values.
"""
import os
from typing import Optional

from core.config import (
    LANGUAGES as CORE_LANGUAGES,
    QUALITIES as CORE_QUALITIES,
    SEASONS as CORE_SEASONS,
    CUSTOM_FILE_CAPTION,
    BATCH_FILE_CAPTION,
    AUTH_CHANNELS,
    MOVIE_UPDATE_CHANNEL,
    SUPPORT_CHAT,
    TMDB_API_KEY,
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ───────── Search behaviour ─────────
SEARCH_PAGE_SIZE = _env_int("SEARCH_PAGE_SIZE", 10)
MAX_SEARCH_RESULTS = _env_int("MAX_SEARCH_RESULTS", 200)
MAX_RELEASES_PER_TITLE = _env_int("MAX_RELEASES_PER_TITLE", 30)
MAX_EPISODES_PER_PAGE = _env_int("MAX_EPISODES_PER_PAGE", 20)

SEARCH_CACHE_TTL = _env_int("SEARCH_CACHE_TTL", 300)     # seconds
SESSION_TTL = _env_int("SEARCH_SESSION_TTL", 1800)        # 30 min
SHARD_TIMEOUT = _env_int("SEARCH_SHARD_TIMEOUT", 6)       # seconds per shard
SHARD_CONCURRENCY = _env_int("SEARCH_SHARD_CONCURRENCY", 10)

# ───────── Metadata provider ─────────
METADATA_PROVIDER = os.getenv("METADATA_PROVIDER", "tmdb").strip().lower()
METADATA_API_KEY = os.getenv("METADATA_API_KEY", TMDB_API_KEY or "")
METADATA_TIMEOUT = _env_int("METADATA_TIMEOUT", 3)
METADATA_CACHE_TTL = _env_int("METADATA_CACHE_TTL", 3600)
METADATA_ENABLED = _env_bool("METADATA_ENABLED", bool(METADATA_API_KEY))

# ───────── Subscription ─────────
FORCE_SUB_ENABLED = _env_bool("FORCE_SUB_ENABLED", bool(AUTH_CHANNELS))

# ───────── Preferred release ─────────
PREFERRED_QUALITY = os.getenv("PREFERRED_QUALITY", "1080p")
PREFERRED_CODEC = os.getenv("PREFERRED_CODEC", "HEVC")
PREFERRED_AUDIO = os.getenv("PREFERRED_AUDIO", "ENGLISH")
PREFERRED_SUBTITLE = os.getenv("PREFERRED_SUBTITLE", "ENGLISH")

# ───────── Captions ─────────
DEFAULT_FILE_CAPTION = CUSTOM_FILE_CAPTION or (
    "🎬 <b>{title}</b> ({year})\n"
    "\n"
    "🎞️ Qᴜᴀʟɪᴛʏ: <code>{quality}</code>\n"
    "🧬 Cᴏᴅᴇᴄ: <code>{codec}</code>\n"
    "🔊 Aᴜᴅɪᴏ: <code>{audio}</code>\n"
    "📝 Sᴜʙᴛɪᴛʟᴇ: <code>{subtitle}</code>\n"
    "💾 Sɪᴢᴇ: <code>{size}</code>\n"
    "\n"
    "🔎 Sᴇᴀʀᴄʜ Mᴏʀᴇ: {group_link}"
)
DEFAULT_BATCH_CAPTION = BATCH_FILE_CAPTION or (
    "📺 <b>{series_title}</b>\n"
    "🎞️ Sᴇᴀꜱᴏɴ {season} · Eᴘɪꜱᴏᴅᴇ {episode}\n"
    "\n"
    "🎞️ Qᴜᴀʟɪᴛʏ: <code>{quality}</code>\n"
    "🧬 Cᴏᴅᴇᴄ: <code>{codec}</code>\n"
    "🔊 Aᴜᴅɪᴏ: <code>{audio}</code>\n"
    "💾 Sɪᴢᴇ: <code>{size}</code>\n"
    "\n"
    "🔎 Sᴇᴀʀᴄʜ Mᴏʀᴇ: {group_link}"
)

# ───────── Canonical maps (reuse core) ─────────
LANGUAGES = CORE_LANGUAGES           # {"ᴍᴀʟᴀʏᴀʟᴀᴍ": "mal", ...}
QUALITIES = CORE_QUALITIES           # ["360P", "480P", "720P", "1080P", ...]
SEASONS = CORE_SEASONS               # ["S01", "S02", ...]

# ───────── Links ─────────
SUPPORT_CHAT_URL = SUPPORT_CHAT
UPDATE_CHANNEL_URL = os.getenv("UPDATE_CHNL_LNK", "https://t.me/")
MOVIE_UPDATE_CHANNEL_ID: Optional[int] = None
try:
    if MOVIE_UPDATE_CHANNEL:
        MOVIE_UPDATE_CHANNEL_ID = int(MOVIE_UPDATE_CHANNEL)
except (TypeError, ValueError):
    MOVIE_UPDATE_CHANNEL_ID = None
