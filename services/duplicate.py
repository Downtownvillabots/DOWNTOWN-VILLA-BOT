"""
DOWNTOWN VILLA — Duplicate detection via SHA-256 fingerprint.
Stable across Telegram file_reference rotations.
"""
import hashlib
import logging
import re
from collections import deque

logger = logging.getLogger(__name__)

try:
    from pyrogram.file_id import FileId
    _HAS_FILEID = True
except Exception:
    _HAS_FILEID = False
    logger.warning("[DUP] pyrogram.file_id unavailable — fingerprint disabled")


_NORM_RE = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    """Collapse to lowercase alphanumeric for search."""
    if not name:
        return ""
    base = name.rsplit(".", 1)[0]
    return _NORM_RE.sub("", base.lower())


def compute_fingerprint(tg_file_id: str) -> str:
    """
    Stable SHA-256 from (file_type, dc_id, media_id, access_hash).
    Excludes file_reference which rotates.
    """
    if not _HAS_FILEID or not tg_file_id:
        logger.debug(f"[DUP] no FileId module; hashing raw file_id")
        return hashlib.sha256((tg_file_id or "").encode("utf-8")).hexdigest()
    try:
        d = FileId.decode(tg_file_id)
        raw = f"{d.file_type}|{d.dc_id}|{d.media_id}|{d.access_hash}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
    except Exception as e:
        # Decode failed — fallback hashing is unreliable but prevents crashes.
        logger.warning(f"[DUP] decode failed, using raw hash: {type(e).__name__}: {e}")
        return hashlib.sha256((tg_file_id or "").encode("utf-8")).hexdigest()


# ── In-memory bloom (LRU bounded) ──
_recent = set()
_order = deque()
_MAX = 100_000


def _bloom_check(fp: str) -> bool:
    return fp in _recent


def _bloom_add(fp: str) -> None:
    if fp in _recent:
        return
    _recent.add(fp)
    _order.append(fp)
    while len(_order) > _MAX:
        old = _order.popleft()
        _recent.discard(old)


# ── Duplicate check across all media shards ──
async def is_duplicate(tg_file_id: str) -> bool:
    """Check ALL media shards for this fingerprint. Fast path via bloom."""
    fp = compute_fingerprint(tg_file_id)
    if _bloom_check(fp):
        return True

    from database import db_registry
    for entry in db_registry.media_entries():
        try:
            doc = await entry.db["media_files"].find_one({"_id": fp}, {"_id": 1})
            if doc:
                _bloom_add(fp)
                return True
        except Exception as e:
            logger.warning(f"[DUP] check failed on shard {entry.index}: {e}")
    return False


def remember(fp: str) -> None:
    _bloom_add(fp)
