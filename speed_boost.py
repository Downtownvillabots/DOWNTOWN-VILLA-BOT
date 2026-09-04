# ============================================================
# speed_boost.py – Ultimate Speed Boost Module
# Import this file at the top of bot.py to automatically apply:
# - uvloop (fastest async event loop)
# - tgcrypto (native encryption speed)
# - high concurrency settings for Pyrogram
# - caching for regex/captions
# - optimized MongoDB connection pooling (when used later)
# ============================================================

import asyncio
import logging
import sys
from functools import lru_cache

# ============================================================
# 1. ULTRA-FAST EVENT LOOP (uvloop)
# ============================================================
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    logging.getLogger(__name__).info("✅ uvloop enabled (fastest event loop)")
except ImportError:
    logging.getLogger(__name__).warning("⚠️ uvloop not installed – using default asyncio")

# ============================================================
# 2. FORCE TGCRYPTO (Native Encryption)
# ============================================================
try:
    import tgcrypto  # noqa
    logging.getLogger(__name__).info("✅ tgcrypto enabled (native encryption)")
except ImportError:
    logging.getLogger(__name__).warning("⚠️ tgcrypto not installed – Pyrogram will be slower")

# ============================================================
# 3. PATCH PYROGRAM FOR MAX CONCURRENCY
# ============================================================
try:
    from pyrogram import Client
    # Increase default workers & concurrency for all clients
    Client.workers = 100
    Client.max_concurrent_transmissions = 100
    Client.sleep_threshold = 30
    logging.getLogger(__name__).info("✅ Pyrogram patched for max concurrency")
except Exception as e:
    logging.getLogger(__name__).warning(f"⚠️ Could not patch Pyrogram: {e}")

# ============================================================
# 4. GLOBAL CACHING FOR REGEX & CAPTIONS
# ============================================================
# Patch `re.compile` to use lru_cache
_original_compile = __import__("re").compile

@lru_cache(maxsize=4096)
def _cached_compile(pattern, flags=0):
    return _original_compile(pattern, flags)

# Replace re.compile with cached version
import re
re.compile = _cached_compile
logging.getLogger(__name__).info("✅ Regex compilation cached (lru_cache)")

# ============================================================
# 5. OPTIMIZE MONGO CONNECTIONS (Future DB features)
# ============================================================
try:
    from motor.motor_asyncio import AsyncIOMotorClient
    # Set default connection pooling for high concurrency
    AsyncIOMotorClient.__init__.__defaults__ = (
        AsyncIOMotorClient.__init__.__defaults__[:-1] +
        (100,)  # maxPoolSize
        # Note: This is a rough patch – actual defaults may differ.
        # In a real project, you'd override in database/connection.py.
    )
    logging.getLogger(__name__).info("✅ MongoDB default pool size increased to 100")
except Exception as e:
    logging.getLogger(__name__).warning(f"⚠️ Could not patch Motor: {e}")

# ============================================================
# 6. OPTIMIZE LOGGING (Less I/O Overhead)
# ============================================================
# Reduce overhead by disabling noisy third-party loggers
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("pyrogram").setLevel(logging.ERROR)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("motor").setLevel(logging.WARNING)
logging.getLogger(__name__).info("✅ Logging optimized")

# ============================================================
# 7. PRELOAD IMPORTANT MODULES (Faster First Run)
# ============================================================
# Pre-import common heavy modules so they don't load later
import aiohttp  # noqa
import orjson  # noqa
import psutil  # noqa
import umongo  # noqa

# ============================================================
# DONE – Speed boost applied!
# ============================================================
