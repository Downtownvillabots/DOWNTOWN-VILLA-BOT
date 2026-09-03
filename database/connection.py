import logging
from motor.motor_asyncio import AsyncIOMotorClient
from urllib.parse import urlparse
from config import (
    DATABASE_URI, DATABASE_NAME, MEDIA_DATABASE_URIS, DB_CONNECTION_TIMEOUT, DB_RETRY_COUNT
)

logger = logging.getLogger(__name__)

_user_client = None
_user_db = None
_media_clients = []
_media_dbs = []
_media_labels = []

def get_db_label(uri):
    try:
        parsed = urlparse(uri)
        return parsed.hostname or "unknown"
    except:
        return "unknown"

def get_user_db():
    global _user_client, _user_db
    if _user_db is None:
        _user_client = AsyncIOMotorClient(DATABASE_URI, serverSelectionTimeoutMS=DB_CONNECTION_TIMEOUT)
        _user_db = _user_client[DATABASE_NAME]
        logger.info(f"Connected to user DB: {get_db_label(DATABASE_URI)}")
    return _user_db

def _initialize_media_pool():
    global _media_clients, _media_dbs, _media_labels
    _media_clients = []
    _media_dbs = []
    _media_labels = []
    for uri in MEDIA_DATABASE_URIS:
        for attempt in range(DB_RETRY_COUNT):
            try:
                client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=DB_CONNECTION_TIMEOUT)
                db = client[DATABASE_NAME]
                _media_clients.append(client)
                _media_dbs.append(db)
                _media_labels.append(get_db_label(uri))
                break
            except Exception as e:
                logger.error(f"Attempt {attempt+1} failed for {uri}: {e}")
                if attempt == DB_RETRY_COUNT - 1:
                    logger.warning(f"Could not connect to {uri}, skipping.")
                else:
                    import asyncio
                    asyncio.sleep(2)
    if not _media_dbs:
        logger.warning("No media DBs, using user DB as fallback.")
        _media_dbs.append(get_user_db())
        _media_labels.append(get_db_label(DATABASE_URI))

def get_media_dbs():
    if not _media_dbs:
        _initialize_media_pool()
    return _media_dbs

def get_media_collections():
    from config import COLLECTION_NAME
    return [db[COLLECTION_NAME] for db in get_media_dbs()]

def get_media_labels():
    if not _media_dbs:
        _initialize_media_pool()
    return _media_labels

# Initialize pool on import
_initialize_media_pool()