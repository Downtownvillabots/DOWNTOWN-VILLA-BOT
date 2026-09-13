"""
Media file storage repository.
Uses SHA-256 fingerprint as `_id` for global deduplication.
Stores raw Telegram file_id separately for delivery.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from database.media.routing import media_router
from database.media.duplicates import duplicate_checker
from services.duplicate import compute_fingerprint, normalize_name, remember

logger = logging.getLogger(__name__)


class MediaFileRepository:
    async def add_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save a fully-parsed media record.
        Returns {status, shard_index, reason, record}.
        Status: 'saved' | 'duplicate' | 'error'
        """
        file_id = record.get("file_id") or ""
        if not file_id:
            return {"status": "error", "shard_index": None,
                    "reason": "no_file_id", "record": None}

        # ── Fingerprint + cross-shard exact check ──
        fp = compute_fingerprint(file_id)
        record["_id"] = fp
        record["norm_name"] = normalize_name(record.get("file_name") or "")

        from services.duplicate import _bloom_check  # type: ignore
        from database import db_registry

        # Bloom fast-path
        if _bloom_check(fp):
            logger.info(f"[IDX] ♻️ dup (bloom) file='{record.get('file_name')}'")
            return {"status": "duplicate", "shard_index": None,
                    "reason": "exact", "record": None}

        # Exact match across shards
        for entry in db_registry.media_entries():
            try:
                exists = await entry.db["media_files"].find_one({"_id": fp}, {"_id": 1})
                if exists:
                    remember(fp)
                    logger.info(f"[IDX] ♻️ dup (shard) file='{record.get('file_name')}' shard=DB{entry.index}")
                    return {"status": "duplicate", "shard_index": entry.index,
                            "reason": "exact", "record": None}
            except Exception:
                pass

        # ── Logical duplicate check (title + quality + codec) ──
        existing, shard = await duplicate_checker.check_all(record)
        if existing:
            logger.info(
                f"[IDX] ♻️ dup (logical) file='{record.get('file_name')}'"
            )
            return {"status": "duplicate", "shard_index": shard,
                    "reason": "logical", "record": existing}

        # ── Route to correct shard ──
        try:
            shard_index, db = await media_router.pick_shard()
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return {"status": "error", "shard_index": None,
                    "reason": str(e), "record": None}

        # ── Enrich ──
        record = dict(record)
        record["logical_identity"] = duplicate_checker.logical_identity(record)
        record["indexed_at"] = datetime.utcnow()
        record["shard_index"] = shard_index

        # ── Insert ──
        try:
            await db["media_files"].insert_one(record)
        except Exception as e:
            if "DuplicateKey" in str(e) or "duplicate key" in str(e).lower():
                remember(fp)
                return {"status": "duplicate", "shard_index": shard_index,
                        "reason": "exact", "record": None}
            logger.exception("Insert failed")
            return {"status": "error", "shard_index": shard_index,
                    "reason": str(e), "record": None}

        remember(fp)
        logger.info(
            f"[IDX] ✅ stored file='{record.get('file_name')}' "
            f"title='{record.get('title')}' shard=DB{shard_index + 1}"
        )
        return {"status": "saved", "shard_index": shard_index,
                "reason": None, "record": record}

    async def count_all(self) -> int:
        from database import db_registry
        total = 0
        for entry in db_registry.media_entries():
            try:
                total += await entry.db["media_files"].estimated_document_count()
            except Exception:
                pass
        return total


media_files_repo = MediaFileRepository()
