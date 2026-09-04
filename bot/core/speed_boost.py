# ============================================================
# speed_boost.py – Ultimate Speed Boost Module
# Import at the very top of main.py to apply:
# - uvloop (fastest async event loop)
# - tgcrypto (native encryption)
# - max Pyrogram concurrency (safe for Render)
# - global regex compilation caching
# - silence noisy logs
# ============================================================

import asyncio
import logging
import re
from functools import lru_cache

log = logging.getLogger("speed_boost")

# 1. ULTRA-FAST EVENT LOOP
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    log.info("✅ uvloop enabled")
except ImportError:
    log.warning("⚠️ uvloop not installed – using default asyncio")

# 2. TGCRYPTO (Pyrogram auto-detects; we just import to verify)
try:
    import tgcrypto  # noqa
    log.info("✅ tgcrypto enabled")
except ImportError:
    log.warning("⚠️ tgcrypto not installed – Pyrogram will be slower")

# 3. PYROGRAM CONCURRENCY (safe for Render free tier)
try:
    from pyrogram import Client
    # Use 4 workers – safe for Render, still fast
    Client.workers = 4
    Client.sleep_threshold = 30
    log.info("✅ Pyrogram workers set to 4")
except Exception:
    pass

# 4. GLOBAL REGEX COMPILATION CACHE
_original_compile = re.compile

@lru_cache(maxsize=4096)
def _cached_compile(pattern, flags=0):
    return _original_compile(pattern, flags)

re.compile = _cached_compile
log.info("✅ Regex compilation cached globally")

# 5. SILENCE NOISY LOGS (even if logging not yet configured, it's fine)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("motor").setLevel(logging.WARNING)
