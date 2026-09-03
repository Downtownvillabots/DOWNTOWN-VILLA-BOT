# ============================================================
# database/files.py – Media file DB operations (unlimited DB pool)
# Uses get_media_dbs() and get_media_collections() from connection.py
# ============================================================

import logging
import asyncio
import re
import base64
from struct import pack
from typing import List, Dict, Optional, Tuple
from functools import lru_cache

from pyrogram.file_id import FileId
from pymongo.errors import DuplicateKeyError, OperationFailure
from umongo import Instance, Document, fields, ValidationError

from database.connection import get_media_dbs, get_media_collections, get_media_labels
from config import (
    COLLECTION_NAME,
    COVERX,
    INDEX_CAPTION,
    USE_CAPTION_FILTER,
    ULTRA_FAST_MODE,
    MAX_B_TN,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# Model Registration (per database)
# ============================================================
def _create_model(instance: Instance):
    class MediaModel(Document):
        file_id = fields.StrField(attribute="_id")
        file_ref = fields.StrField(allow_none=True)
        file_name = fields.StrField(required=True)
        file_size = fields.IntField(required=True)
        file_type = fields.StrField(allow_none=True)
        mime_type = fields.StrField(allow_none=True)
        caption = fields.StrField(allow_none=True)
        cover = fields.StrField(allow_none=True)

        class Meta:
            collection_name = COLLECTION_NAME

        @classmethod
        async def ensure_indexes(cls):
            if cls.collection is not None:
                await cls.collection.create_index([("file_name", 1)])

    instance.register(MediaModel)
    return MediaModel

# Initialize models across all media DBs
MODELS = []
DBS = get_media_dbs()
COLLECTIONS = get_media_collections()
DB_LABELS = get_media_labels()

for db in DBS:
    inst = Instance.from_db(db)
    model = _create_model(inst)
    MODELS.append(model)

# Backward compatibility aliases
Media = MODELS[0] if MODELS else None
Media2 = MODELS[1] if len(MODELS) > 1 else Media
Media3 = MODELS[2] if len(MODELS) > 2 else Media2

# ============================================================
# Database Size Cache
# ============================================================
_db_stats_cache = {"timestamp": None, "primary_size": 0.0}

async def check_db_size(database) -> float:
    import time
    from datetime import datetime, timedelta
    try:
        now = datetime.utcnow()
        cache_stale = (
            _db_stats_cache["timestamp"] is None
            or (now - _db_stats_cache["timestamp"] > timedelta(minutes=10))
        )
        if not cache_stale and _db_stats_cache["primary_size"] < 10.0:
            return _db_stats_cache["primary_size"]
        stats = await database.command("dbstats")
        size_mb = (stats["dataSize"] + stats["indexSize"]) / (1024 * 1024)
        _db_stats_cache["primary_size"] = size_mb
        _db_stats_cache["timestamp"] = now
        return size_mb
    except Exception as e:
        logger.error(f"[DB] Error checking size: {e}")
        return 0

# ============================================================
# Save File
# ============================================================
async def save_file(media):
    try:
        file_id, file_ref = unpack_new_file_id(media.file_id)
    except Exception as e:
        logger.error(f"[SAVE] Failed to unpack file ID: {e}")
        return False, 3

    file_name = re.sub(
        r"[_\-\.#+$%^&*()!~`,;:\"'?/<>\[\]{}=|\\]", " ", str(media.file_name)
    )
    file_name = re.sub(r"\s+", " ", file_name).strip()
    if not file_name:
        file_name = "Unknown File"

    # Duplicate check across all collections
    for idx, collection in enumerate(COLLECTIONS):
        try:
            exists = await collection.find_one({"file_id": file_id})
            if exists:
                logger.info(f"[SKIP] '{file_name}' already in DB{idx+1} ({DB_LABELS[idx]})")
                return False, 0
        except Exception as e:
            logger.error(f"[SAVE] Duplicate check error DB{idx+1}: {e}")

    # Choose smallest DB (or first below threshold)
    target_index = 0
    if len(DBS) > 1:
        min_size = float("inf")
        for idx, database in enumerate(DBS):
            size = await check_db_size(database)
            if size < min_size:
                min_size = size
                target_index = idx

    target_model = MODELS[target_index]
    target_db_name = f"DB{target_index+1} ({DB_LABELS[target_index]})"

    try:
        cover_to_use = getattr(getattr(media, "cover", None), "file_id", None)
        record = target_model(
            file_id=file_id,
            file_ref=file_ref,
            file_name=file_name,
            file_size=getattr(media, "file_size", 0),
            file_type=getattr(media, "file_type", None),
            mime_type=getattr(media, "mime_type", None),
            caption=(media.caption.html if media.caption and INDEX_CAPTION else None),
            cover=cover_to_use if COVERX else None,
        )
    except ValidationError as e:
        logger.error(f"[ERROR] Validation failed for '{file_name}': {e}")
        return False, 2
    except Exception as e:
        logger.error(f"[ERROR] '{file_name}' - {e}")
        return False, 3

    try:
        await record.commit()
        logger.info(f"[SUCCESS] Saved '{file_name}' to {target_db_name}")
        return True, 1
    except DuplicateKeyError:
        logger.info(f"[SKIP] DuplicateKey '{file_name}' already in {target_db_name}")
        return False, 0
    except OperationFailure as e:
        logger.error(f"[DB] Operation failure in {target_db_name}: {e}")
        if target_index + 1 < len(MODELS):
            try:
                record2 = MODELS[target_index + 1](**record.to_mongo())
                await record2.commit()
                logger.info(f"[SUCCESS] Saved '{file_name}' to DB{target_index+2}")
                return True, 1
            except Exception:
                pass
        return False, 3
    except Exception as e:
        logger.error(f"[ERROR] Commit failed '{file_name}': {e}")
        return False, 3

# ============================================================
# Search Results
# ============================================================
async def get_search_results(chat_id, query, file_type=None, max_results=None, offset=0, filter=False):
    from config import MAX_B_TN
    from utils import get_settings, save_group_settings

    if chat_id is not None and max_results is None:
        settings = await get_settings(int(chat_id))
        if "max_btn" not in settings:
            await save_group_settings(int(chat_id), "max_btn", True)
            settings["max_btn"] = True
        max_results = 10 if settings["max_btn"] else int(MAX_B_TN)

    # Build regex
    if isinstance(query, list):
        raw_pattern = "|".join(re.escape(q.strip()) for q in query if q and q.strip())
        if not raw_pattern:
            return [], None, 0
        regex = compile_regex(raw_pattern)
        filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}
    else:
        query = query.strip()
        if not query:
            return [], None, 0
        if " " in query:
            words = [re.escape(w) for w in query.split() if w]
            raw_pattern = r".*[\s\.\+\-_]".join(words) if words else r"."
        else:
            raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
        try:
            regex = compile_regex(raw_pattern)
        except re.error:
            return [], None, 0
        filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}

    if file_type:
        filter_mongo["file_type"] = file_type

    try:
        if ULTRA_FAST_MODE:
            limit = max_results + 1
            fetch_limit = offset + limit
            tasks = [
                collection.find(filter_mongo)
                .sort("$natural", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
                for collection in COLLECTIONS
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            files = []
            for res in results:
                if isinstance(res, Exception):
                    logger.error(f"[SEARCH] DB error: {res}")
                    continue
                files.extend(res)
            files = files[offset:offset + limit]
            has_next = len(files) > max_results
            if has_next:
                files = files[:-1]
            next_offset = offset + len(files) if has_next else ""
            total_results = offset + len(files) + (1 if has_next else 0)
        else:
            fetch_limit = offset + max_results
            count_tasks = [collection.count_documents(filter_mongo) for collection in COLLECTIONS]
            find_tasks = [
                collection.find(filter_mongo)
                .sort("$natural", -1)
                .limit(fetch_limit)
                .to_list(length=fetch_limit)
                for collection in COLLECTIONS
            ]
            count_results, find_results = await asyncio.gather(
                asyncio.gather(*count_tasks, return_exceptions=True),
                asyncio.gather(*find_tasks, return_exceptions=True),
            )
            total_results = 0
            for cr in count_results:
                if isinstance(cr, Exception):
                    logger.error(f"[SEARCH] Count error: {cr}")
                else:
                    total_results += cr
            files = []
            for fr in find_results:
                if isinstance(fr, Exception):
                    logger.error(f"[SEARCH] Find error: {fr}")
                else:
                    files.extend(fr)
            files = files[offset:offset + max_results]
            next_offset = offset + len(files)
            if next_offset >= total_results:
                next_offset = ""
    except Exception as e:
        logger.exception(f"[SEARCH] Search failed: {e}")
        return [], "", 0

    return files, next_offset, total_results

# ============================================================
# Other Functions
# ============================================================
async def get_bad_files(query, file_type=None):
    query = query.strip()
    if not query:
        return [], 0
    if " " not in query:
        raw_pattern = r"(\b|[\.\+\-_])" + re.escape(query) + r"(\b|[\.\+\-_])"
    else:
        raw_pattern = r".*[\s\.\+\-_]".join(map(re.escape, query.split()))
    try:
        regex = compile_regex(raw_pattern)
    except re.error:
        return [], 0
    filter_mongo = {"$or": [{"file_name": regex}, {"caption": regex}]} if USE_CAPTION_FILTER else {"file_name": regex}
    if file_type:
        filter_mongo["file_type"] = file_type

    tasks = [collection.find(filter_mongo).sort("$natural", -1).to_list(300) for collection in COLLECTIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    files = []
    for res in results:
        if isinstance(res, Exception):
            continue
        files.extend(res)
    return files[:300], len(files[:300])

async def get_file_details(query):
    filter = {"file_id": query}
    tasks = [collection.find(filter).to_list(length=1) for collection in COLLECTIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            continue
        if res:
            return res
    return []

def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0
    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0
            r += bytes([i])
    return base64.urlsafe_b64encode(r).decode().rstrip("=")

def encode_file_ref(file_ref: bytes) -> str:
    return base64.urlsafe_b64encode(file_ref).decode().rstrip("=")

def unpack_new_file_id(new_file_id):
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(pack("<iiqq", int(decoded.file_type), decoded.dc_id, decoded.media_id, decoded.access_hash))
    file_ref = encode_file_ref(decoded.file_reference)
    return file_id, file_ref

# ============================================================
# DreamxBotz Media Helpers
# ============================================================
async def dreamxbotz_fetch_media(limit: int = 20) -> List[dict]:
    try:
        if len(DBS) > 1:
            for idx, database in enumerate(DBS):
                size = await check_db_size(database)
                if size < 407:
                    cursor = COLLECTIONS[idx].find().sort("$natural", -1).limit(limit)
                    return await cursor.to_list(length=limit)
        cursor = COLLECTIONS[0].find().sort("$natural", -1).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"[MEDIA] Fetch error: {e}")
        return []

async def dreamxbotz_clean_title(filename: str, is_series: bool = False) -> str:
    try:
        year_match = re.search(r"^(.*?(\d{4}|\(\d{4}\)))", filename, re.IGNORECASE)
        if year_match:
            title = year_match.group(1).replace("(", "").replace(")", "")
            return re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title).strip().title()
        if is_series:
            season_match = re.search(r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?", filename, re.IGNORECASE)
            if season_match:
                title = season_match.group(1).strip()
                season = season_match.group(2) or season_match.group(3) or season_match.group(4)
                title = re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", title).strip().title()
                return f"{title} S{int(season):02}"
        return re.sub(r"(?:@[^ \n\r\t.,:;!?()\[\]{}<>\\\/\"'=_%]+|[._\-\[\]@()]+)", " ", filename).strip().title()
    except Exception as e:
        logger.error(f"[MEDIA] Clean title error: {e}")
        return filename

async def dreamxbotz_get_movies(limit: int = 20) -> List[str]:
    try:
        cursor = await dreamxbotz_fetch_media(limit * 2)
        results = set()
        pattern = r"(?:s\d{1,2}|season\s*\d+|season\d+)(?:\s*combined)?(?:e\d{1,2}|episode\s*\d+)?\b"
        for file in cursor:
            file_name = getattr(file, "file_name", "")
            if not re.search(pattern, file_name, re.IGNORECASE):
                title = await dreamxbotz_clean_title(file_name)
                results.add(title)
            if len(results) >= limit:
                break
        return sorted(list(results))[:limit]
    except Exception as e:
        logger.error(f"[MEDIA] Get movies error: {e}")
        return []

async def dreamxbotz_get_series(limit: int = 30) -> Dict[str, List[int]]:
    try:
        cursor = await dreamxbotz_fetch_media(limit * 5)
        grouped = defaultdict(list)
        pattern = r"(.*?)(?:S(\d{1,2})|Season\s*(\d+)|Season(\d+))(?:\s*Combined)?(?:E(\d{1,2})|Episode\s*(\d+))?\b"
        for file in cursor:
            file_name = getattr(file, "file_name", "")
            match = re.search(pattern, file_name, re.IGNORECASE)
            if match:
                title = await dreamxbotz_clean_title(match.group(1), is_series=True)
                season = int(match.group(2) or match.group(3) or match.group(4))
                grouped[title].append(season)
        return {title: sorted(set(seasons))[:10] for title, seasons in grouped.items() if seasons}
    except Exception as e:
        logger.error(f"[MEDIA] Get series error: {e}")
        return {}

# ============================================================
# Additional Utilities
# ============================================================
async def get_total_file_count() -> int:
    total = 0
    for collection in COLLECTIONS:
        try:
            total += await collection.count_documents({})
        except Exception:
            pass
    return total

async def delete_file(file_id: str) -> bool:
    deleted = False
    for collection in COLLECTIONS:
        try:
            result = await collection.delete_one({"_id": file_id})
            if result.deleted_count:
                deleted = True
        except Exception:
            pass
    return deleted

async def clear_all_files() -> int:
    total = 0
    for collection in COLLECTIONS:
        try:
            result = await collection.delete_many({})
            total += result.deleted_count
        except Exception:
            pass
    return total

# ============================================================
# Regex Cache
# ============================================================
@lru_cache(maxsize=4096)
def compile_regex(pattern: str):
    return re.compile(pattern, re.IGNORECASE)