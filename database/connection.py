import logging
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional
from database.config import DatabaseConfig

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self._system_client: Optional[AsyncIOMotorClient] = None
        self._user_client: Optional[AsyncIOMotorClient] = None
        self._catalog_client: Optional[AsyncIOMotorClient] = None
        self._media_clients: List[AsyncIOMotorClient] = []
        self._system_db = None
        self._user_db = None
        self._catalog_db = None
        self._media_dbs = []
        self._initialized = False
        self._db_enabled = False

    async def initialize(self):
        if self._initialized:
            return

        system_uri = DatabaseConfig.get_system_uri()
        if not system_uri:
            logger.warning("SYSTEM_DATABASE_01 is not set. Database features disabled.")
            self._initialized = True
            return

        try:
            # System
            self._system_client = AsyncIOMotorClient(system_uri)
            system_db_name = DatabaseConfig.get_system_db_name()
            self._system_db = self._system_client[system_db_name]
            logger.info(f"Connected to System MongoDB: {system_db_name}")

            # User
            user_uri = DatabaseConfig.get_user_uri()
            if user_uri and user_uri != system_uri:
                self._user_client = AsyncIOMotorClient(user_uri)
                user_db_name = DatabaseConfig.get_user_db_name()
                self._user_db = self._user_client[user_db_name]
                logger.info(f"Connected to User MongoDB: {user_db_name}")
            else:
                self._user_db = self._system_db
                logger.info("User database not set, using System database.")

            # Catalog (optional)
            catalog_uri = DatabaseConfig.get_catalog_uri()
            if catalog_uri and catalog_uri not in (system_uri, user_uri):
                self._catalog_client = AsyncIOMotorClient(catalog_uri)
                catalog_db_name = DatabaseConfig.get_catalog_db_name()
                self._catalog_db = self._catalog_client[catalog_db_name]
                logger.info(f"Connected to Catalog MongoDB: {catalog_db_name}")
            else:
                self._catalog_db = self._user_db
                logger.info("Catalog database not set, using User database.")

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

    def get_system_db(self):
        return self._system_db

    def get_user_db(self):
        return self._user_db

    def get_catalog_db(self):
        return self._catalog_db

    def get_media_db(self, index: int = 0):
        if not self._media_dbs:
            return self._user_db
        if index < len(self._media_dbs):
            return self._media_dbs[index]
        return self._media_dbs[0]

    def get_media_db_count(self) -> int:
        return len(self._media_dbs)

    async def close(self):
        if self._system_client:
            self._system_client.close()
        if self._user_client:
            self._user_client.close()
        if self._catalog_client:
            self._catalog_client.close()
        for client in self._media_clients:
            client.close()
        logger.info("Database connections closed.")
