import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from database.config import DatabaseConfig

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Simple database manager for DOWNTOWN VILLA BOT.

    Currently uses a single MongoDB database for all categories.
    This can be expanded later to multiple databases per category.
    """

    def __init__(self):
        self._client: Optional[AsyncIOMotorClient] = None
        self._db: Optional[AsyncIOMotorDatabase] = None
        self._initialized = False
        self._db_enabled = False

    async def initialize(self):
        """Connect to the main MongoDB database."""
        if self._initialized:
            return

        uri = DatabaseConfig.get_database_uri()
        if not uri:
            logger.warning("No DATABASE_URI set. Database features disabled.")
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
    def is_db_enabled(self) -> bool:
        return self._db_enabled

    # Accessors (all return the same db for now, later can be split)
    def get_system_db(self) -> Optional[AsyncIOMotorDatabase]:
        return self._db

    def get_user_db(self) -> Optional[AsyncIOMotorDatabase]:
        return self._db

    def get_media_db(self) -> Optional[AsyncIOMotorDatabase]:
        return self._db

    async def close(self):
        if self._client:
            self._client.close()
            logger.info("Database connection closed.")
