"""
Media file storage repository.
Stores Telegram file references + searchable metadata.
No file downloads. No local cache.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from database.media.routing import media_router
from database.media.duplicates import duplicate_checker

logger = logging.getLogger(__name__)


class MediaFileRepository:
    async def add_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save a fully-parsed media record.
        Returns {status, shard_index, reason, record}.
        Status: 'saved' | 'duplicate' | 'error'
        """
        # 1. Duplicate check (exact, then logical)
        existing, shard = await duplicate_checker.check_all(record)
        if existing:
            logger.info(
                f"[IDX] duplicate detected file='{record.get('file_name')}' "
                f"existing_id={existing.get('file_id')}"
            )
            return {
                "status": "duplicate",
                "shard_index": shard,
                "reason": (
                    "exact"
                    if existing.get("file_unique_id") == record.get("file_unique_id")
                    else "logical"
                ),
                "record": existing,
            }

        # 2. Route to correct shard
        try:
            shard_index, db = await media_router.pick_shard()
        except Exception as e:
            logger.error(f"Routing failed: {e}")
            return {
                "status": "error",
                "shard_index": None,
                "reason": str(e),
                "record": None,
            }

        # 3. Enrich record
        record = dict(record)
        record["logical_identity"] = duplicate_checker.logical_identity(record)
        record["indexed_at"] = datetime.utcnow()
        record["shard_index"] = shard_index

        # 4. Insert
        try:
            await db["media_files"].insert_one(record)
        except Exception as e:
            logger.exception("Insert failed")
            return {
                "status": "error",
                "shard_index": shard_index,
                "reason": str(e),
                "record": None,
            }

        logger.info(
            f"[IDX] stored file='{record.get('file_name')}' "
            f"title='{record.get('title')}' shard=DB{shard_index + 1}"
        )

        return {
            "status": "saved",
            "shard_index": shard_index,
            "reason": None,
            "record": record,
        }

    async def count_all(self) -> int:
        total = 0
        for entry in __import__("database").db_registry.media_entries():
            try:
                total += await entry.db["media_files"].estimated_document_count()
            except Exception:
                pass
        return total


media_files_repo = MediaFileRepository()
