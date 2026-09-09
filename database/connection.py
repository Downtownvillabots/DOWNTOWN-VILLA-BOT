import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from database.config import DatabaseConfig

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self._client = None
        self._db = None
        self._initialized = False
        self._db_enabled = False

    async def initialize(self):
        if self._initialized:
            return

        uri = DatabaseConfig.get_database_uri()
        if not uri:
            # Print environment variables containing "DATABASE" for debugging
            db_env_keys = [k for k in os.environ if "DATABASE" in k.upper() or "MONGO" in k.upper()]
            logger.warning(f"Database environment variables found: {db_env_keys}")
            self._initialized = True
            return

        try:
            self._client = AsyncIOMotorClient(uri)
            db_name = DatabaseConfig.get_database_name()
            self._db = self._client[db_name]
            logger.info(f"Connected to MongoDB database: {db_name}")
            self._db_enabled = True
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            self._db_enabled = False

        self._initialized = True

    @property
    def is_db_enabled(self):
        return self._db_enabled

    def get_system_db(self):
        return self._db

    def get_user_db(self):
        return self._db

    def get_media_db(self):
        return self._db

    async def close(self):
        if self._client:
            self._client.close()
            logger.info("Database connection closed.")
