"""
Common indexing pipeline.
Both manual (backward) and automatic (live) indexing use this.
"""
import logging
from typing import Any, Dict, Optional

from indexing.parsers import extract_metadata
from indexing.classifier import classify_record
from database.media.files import media_files_repo

logger = logging.getLogger(__name__)


def _pick_media(message) -> Optional[Dict[str, Any]]:
    """Extract the primary media from a Pyrogram Message."""
    if message.video:
        v = message.video
        return {"file_id": v.file_id, "file_unique_id": v.file_unique_id,
                "file_name": v.file_name, "file_size": v.file_size,
                "mime_type": v.mime_type, "kind": "video"}
    if message.document:
        d = message.document
        return {"file_id": d.file_id, "file_unique_id": d.file_unique_id,
                "file_name": d.file_name, "file_size": d.file_size,
                "mime_type": d.mime_type, "kind": "document"}
    if message.audio:
        a = message.audio
        return {"file_id": a.file_id, "file_unique_id": a.file_unique_id,
                "file_name": a.file_name, "file_size": a.file_size,
                "mime_type": a.mime_type, "kind": "audio"}
    return None


def _build_record(message, media: Dict[str, Any]) -> Dict[str, Any]:
    caption = message.caption or ""
    meta = extract_metadata(media.get("file_name"), caption)

    record = dict(meta)
    record.update({
        "file_id": media["file_id"],
        "file_unique_id": media.get("file_unique_id"),
        "file_name": media.get("file_name"),
        "file_size": media.get("file_size"),
        "mime_type": media.get("mime_type"),
        "kind": media.get("kind"),
        "channel_id": message.chat.id if message.chat else None,
        "message_id": message.id,
        "caption": caption or None,
    })
    record["type"] = classify_record(record)
    return record


async def process_message(message, mode: str = "auto") -> Dict[str, Any]:
    """
    Process a single Pyrogram message.
    Returns a result dict:
      {status, reason, record, shard_index}
    status: 'saved' | 'duplicate' | 'skipped' | 'error'
    """
    media = _pick_media(message)
    if not media:
        return {"status": "skipped", "reason": "no_media", "record": None, "shard_index": None}

    if not media.get("file_id"):
        return {"status": "skipped", "reason": "no_file_id", "record": None, "shard_index": None}

    try:
        record = _build_record(message, media)
    except Exception as e:
        logger.exception("Metadata extraction failed")
        return {"status": "error", "reason": f"parse:{e}", "record": None, "shard_index": None}

    if not record.get("title"):
        return {"status": "skipped", "reason": "no_title", "record": record, "shard_index": None}

    # Duplicate / save
    try:
        result = await media_files_repo.add_record(record)
    except Exception as e:
        logger.exception("Save failed")
        return {"status": "error", "reason": f"save:{e}", "record": record, "shard_index": None}

    return {
        "status": result["status"],
        "reason": result.get("reason"),
        "record": result.get("record"),
        "shard_index": result.get("shard_index"),
    }
