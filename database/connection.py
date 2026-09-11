import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional
from database.config import DatabaseConfig

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self._core_client: Optional[AsyncIOMotorClient] = None
        self._catalog_client: Optional[AsyncIOMotorClient] = None
        self._media_clients: List[AsyncIOMotorClient] = []
        self._core_db = None
        self._catalog_db = None
        self._media_dbs = []
        self._initialized = False
        self._db_enabled = False

    async def initialize(self):
        if self._initialized:
            return

        core_uri = DatabaseConfig.get_core_uri()
        if not core_uri:
            logger.warning("Core DATABASE_URI is not set. Database features disabled.")
            self._initialized = True
            return

        try:
            # Core
            self._core_client = AsyncIOMotorClient(core_uri)
            core_db_name = DatabaseConfig.get_core_db_name()
            self._core_db = self._core_client[core_db_name]
            logger.info(f"Connected to Core MongoDB: {core_db_name}")

            # Catalog
            catalog_uri = DatabaseConfig.get_catalog_uri()
            if catalog_uri:
                self._catalog_client = AsyncIOMotorClient(catalog_uri)
                catalog_db_name = DatabaseConfig.get_catalog_db_name()
                self._catalog_db = self._catalog_client[catalog_db_name]
                logger.info(f"Connected to Catalog MongoDB: {catalog_db_name}")
            else:
                self._catalog_db = self._core_db
                logger.info("Catalog database not set, using Core database.")

            # Media pool
            media_uris = DatabaseConfig.get_media_uris()
            media_db_name = DatabaseConfig.get_media_db_name()
            for i, uri in enumerate(media_uris):
                client = AsyncIOMotorClient(uri)
                db = client[media_db_name]
                self._media_clients.append(client)
                self._media_dbs.append(db)
                logger.info(f"Connected to Media MongoDB #{i+1}: {media_db_name}")

            self._db_enabled = True
        except Exception as e:
            logger.error(f"Failed to connect to databases: {e}")
            self._db_enabled = False
        finally:
            self._initialized = True

    @property
    def is_db_enabled(self) -> bool:
        return self._db_enabled

    def get_core_db(self):
        return self._core_db

    def get_catalog_db(self):
        return self._catalog_db

    def get_media_db(self, index: int = 0):
        if not self._media_dbs:
            return self._core_db
        if index < len(self._media_dbs):
            return self._media_dbs[index]
        return self._media_dbs[0]

    def get_media_db_count(self) -> int:
        return len(self._media_dbs)

    async def close(self):
        if self._core_client:
            self._core_client.close()
        if self._catalog_client:
            self._catalog_client.close()
        for client in self._media_clients:
            client.close()
        logger.info("Database connections closed.")
