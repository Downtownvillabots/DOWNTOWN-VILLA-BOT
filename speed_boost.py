# ============================================================
# speed_boost.py – Ultimate Speed Boost Module
# Import this at the top of bot.py to apply:
# - uvloop (fastest async event loop)
# - tgcrypto (native encryption)
# - max Pyrogram concurrency (safe for Render)
# - regex/caption caching
# ============================================================

import asyncio
import logging
import re
from functools import lru_cache

# 1. ULTRA-FAST EVENT LOOP
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logging.getLogger(__name__).info("✅ uvloop enabled")
except ImportError:
    logging.getLogger(__name__).warning("⚠️ uvloop not installed – using default asyncio")

# 2. TGCRYPTO
try:
    import tgcrypto  # noqa
    logging.getLogger(__name__).info("✅ tgcrypto enabled")
except ImportError:
    logging.getLogger(__name__).warning("⚠️ tgcrypto not installed – Pyrogram slower")

# 3. PYROGRAM CONCURRENCY (safe for Render free tier – 4 workers)
try:
    from pyrogram import Client
    # Use 4 workers – safe for Render, still fast
    Client.workers = 4
    Client.sleep_threshold = 30
    logging.getLogger(__name__).info("✅ Pyrogram workers set to 4")
except Exception:
    pass

# 4. CACHE REGEX COMPILATION
_original_compile = re.compile

@lru_cache(maxsize=4096)
def _cached_compile(pattern, flags=0):
    return _original_compile(pattern, flags)

re.compile = _cached_compile
logging.getLogger(__name__).info("✅ Regex compilation cached")

# 5. SILENCE NOISY LOGS
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("motor").setLevel(logging.WARNING)
