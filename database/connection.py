import logging
from config import COMPUTER_STORAGE, STORAGE_NAME

logger = logging.getLogger(__name__)

_client = None
_db = None

def get_storage():
    global _client, _db
    if _db is None and COMPUTER_STORAGE:
        from motor.motor_asyncio import AsyncIOMotorClient
        _client = AsyncIOMotorClient(COMPUTER_STORAGE)
        _db = _client[STORAGE_NAME]
        logger.info("Storage connected")
    return _db
