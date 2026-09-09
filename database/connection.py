import asyncio
import logging
from typing import Dict, Optional, List, Union

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from database.config import DatabaseConfig

logger = logging.getLogger(__name__)

class DatabaseManager:
    """
    Central database connection manager for DOWNTOWN VILLA BOT.
    - Reads all environment variables for System/User/Media databases.
    - Creates and manages reusable MongoDB clients.
    - Provides access to individual databases.
    """

    def __init__(self):
        self._clients: Dict[str, AsyncIOMotorClient] = {}
        self._system_dbs: Dict[int, AsyncIOMotorDatabase] = {}
        self._user_dbs: Dict[int, AsyncIOMotorDatabase] = {}
        self._media_dbs: Dict[int, AsyncIOMotorDatabase] = {}
        self._media_db_order: List[int] = []
        self._active_media_db: Optional[int] = None
        self._media_threshold_mb: Optional[int] = None
        self._initialized = False
        self._db_enabled = False

    async def initialize(self):
        """Create all clients and database handles from environment variables."""
        if self._initialized:
            return

        # System databases
        sys_uris = DatabaseConfig.get_system_databases()
        for idx, uri in sys_uris.items():
            client = self._get_client(uri)
            db_name = DatabaseConfig.get_database_name("SYSTEM", idx, "downtown_villa_system")
            self._system_dbs[idx] = client[db_name]
            logger.info(f"System database {idx} connected (db: {db_name}).")

        # User databases
        user_uris = DatabaseConfig.get_user_databases()
        for idx, uri in user_uris.items():
            client = self._get_client(uri)
            db_name = DatabaseConfig.get_database_name("USER", idx, "downtown_villa_users")
            self._user_dbs[idx] = client[db_name]
            logger.info(f"User database {idx} connected (db: {db_name}).")

        # Media databases
        media_uris = DatabaseConfig.get_media_databases()
        self._media_db_order = sorted(media_uris.keys())
        for idx, uri in media_uris.items():
            client = self._get_client(uri)
            db_name = DatabaseConfig.get_database_name("DATABASE", idx, "downtown_villa_media")
            self._media_dbs[idx] = client[db_name]
            logger.info(f"Media database {idx} connected (db: {db_name}).")

        # Set active media db to first available
        if self._media_db_order:
            self._active_media_db = self._media_db_order[0]

        # Threshold
        self._media_threshold_mb = DatabaseConfig.get_media_threshold_mb()
        if self._media_threshold_mb is None:
            self._media_threshold_mb = 400

        # If no databases were configured, mark as disabled
        if not sys_uris and not user_uris and not media_uris:
            self._db_enabled = False
            logger.warning("No database URIs configured. Database features are disabled.")
        else:
            self._db_enabled = True

        self._initialized = True
        logger.info("Database manager initialization complete.")

    def _get_client(self, uri: str) -> AsyncIOMotorClient:
        """Get or create a client for the given URI."""
        if uri not in self._clients:
            self._clients[uri] = AsyncIOMotorClient(uri)
        return self._clients[uri]

    @property
    def is_db_enabled(self) -> bool:
        """Return whether any database is configured."""
        return self._db_enabled

    # ----- Accessors for system databases -----
    def get_system_db(self, index: int = 1) -> Optional[AsyncIOMotorDatabase]:
        return self._system_dbs.get(index)

    # ----- Accessors for user databases -----
    def get_user_db(self, index: int = 1) -> Optional[AsyncIOMotorDatabase]:
        return self._user_dbs.get(index)

    # ----- Accessors for media databases -----
    def get_media_db(self, index: int) -> Optional[AsyncIOMotorDatabase]:
        return self._media_dbs.get(index)

    def get_active_media_db(self) -> Optional[AsyncIOMotorDatabase]:
        if self._active_media_db is not None:
            return self._media_dbs.get(self._active_media_db)
        return None

    def get_active_media_db_index(self) -> Optional[int]:
        return self._active_media_db

    def get_media_db_list(self) -> List[int]:
        return list(self._media_db_order)

    def get_media_threshold(self) -> int:
        return self._media_threshold_mb or 400

    # ----- Basic health check -----
    async def check_health(self) -> Dict:
        """Check connectivity of all databases."""
        status = {"system": {}, "user": {}, "media": {}}
        for idx, db in self._system_dbs.items():
            try:
                await db.command("ping")
                status["system"][idx] = True
            except Exception:
                status["system"][idx] = False
        for idx, db in self._user_dbs.items():
            try:
                await db.command("ping")
                status["user"][idx] = True
            except Exception:
                status["user"][idx] = False
        for idx, db in self._media_dbs.items():
            try:
                await db.command("ping")
                status["media"][idx] = True
            except Exception:
                status["media"][idx] = False
        return status

    async def close(self):
        """Close all MongoDB clients."""
        for client in self._clients.values():
            client.close()
        logger.info("Database connections closed.")
